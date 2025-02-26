import os
import argparse
import json
import subprocess
from git import Repo, GitCommandError, Git
from shutil import rmtree
from distutils.version import LooseVersion

class Gitstaller:
    def __init__(self):
        self.base_dir = os.path.expanduser("~/.gitstaller")
        self.package_dir = os.path.join(self.base_dir, "packages")
        self.metadata_file = os.path.join(self.base_dir, "installed.json")
        self._init_dirs()
        self._load_metadata()

    def _init_dirs(self):
        """Create required directories"""
        os.makedirs(self.package_dir, exist_ok=True)
        if not os.path.exists(self.metadata_file):
            with open(self.metadata_file, 'w') as f:
                json.dump({}, f)

    def _load_metadata(self):
        """Load installed packages metadata"""
        with open(self.metadata_file, 'r') as f:
            self.metadata = json.load(f)

    def _save_metadata(self):
        """Save metadata to file"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def _get_latest_tag(self, repo_url):
        """Get latest release tag from remote repository"""
        g = Git()
        tags = sorted(g.ls_remote(repo_url, tags=True).split('\n'), 
                      key=lambda t: LooseVersion(t.split('/')[-1]), 
                      reverse=True)
        return tags[0].split('\t')[1].split('/')[-1] if tags else None

    def _checkout_version(self, repo, source_spec):
        """Checkout specific version based on source specification"""
        if source_spec == 'main':
            repo.git.checkout('main')
        elif source_spec == 'latest-release':
            tags = sorted(repo.tags, key=lambda t: LooseVersion(t.name), reverse=True)
            if tags:
                repo.git.checkout(tags[0])
            else:
                print("⚠️ No releases found, using main branch")
        else:  # specific version
            repo.git.checkout(source_spec)

    def _build_package(self, install_path):
        """Attempt to build and install the package"""
        try:
            if os.path.exists(os.path.join(install_path, 'Makefile')):
                subprocess.run(['make', '-C', install_path], check=True)
                subprocess.run(
                    ['sudo', 'make', '-C', install_path, 'install'], 
                    check=True
                )
            elif os.path.exists(os.path.join(install_path, 'setup.py')):
                subprocess.run(
                    ['sudo', 'python3', '-m', 'pip', 'install', install_path],
                    check=True
                )
            print("Build and system installation completed successfully")
        except subprocess.CalledProcessError as e:
            print(f"Build failed: {str(e)}")

    def install(self, repo_url, source='main', manual=False, reinstall=False):
        """Install package from Git repository"""
        package_name = self._extract_name(repo_url)
        install_path = os.path.join(self.package_dir, package_name)

        if os.path.exists(install_path) and not reinstall:
            print(f"⚠️ Package {package_name} is already installed")
            return

        try:
            if reinstall and os.path.exists(install_path):
                rmtree(install_path)

            print(f"⏳ Installing {package_name}...")
            
            # Handle different source specifications
            if source == 'latest-release':
                latest_tag = self._get_latest_tag(repo_url)
                if latest_tag:
                    Repo.clone_from(repo_url, install_path, branch=latest_tag)
                else:
                    Repo.clone_from(repo_url, install_path)
            else:
                repo = Repo.clone_from(repo_url, install_path)
                self._checkout_version(repo, source)

            # Build unless manual flag is set
            if not manual:
                self._build_package(install_path)
            
            # Save metadata
            self.metadata[package_name] = {
                "url": repo_url,
                "source": source,
                "manual": manual
            }
            self._save_metadata()
            
            print(f"✅ {package_name} successfully installed")
        except (GitCommandError, PermissionError) as e:
            print(f"❌ Installation error: {str(e)}")

    def update(self, package_name, manual=False):
        """Update installed package"""
        if package_name not in self.metadata:
            print(f"❌ Package {package_name} not found")
            return

        package_path = os.path.join(self.package_dir, package_name)
        try:
            print(f"⏳ Updating {package_name}...")
            repo = Repo(package_path)
            source_spec = self.metadata[package_name].get('source', 'main')
            
            if source_spec == 'latest-release':
                latest_tag = self._get_latest_tag(self.metadata[package_name]['url'])
                if latest_tag:
                    repo.git.fetch('--tags')
                    repo.git.checkout(latest_tag)
            else:
                repo.remotes.origin.pull()
            
            # Rebuild unless manual flag is set
            if not manual and not self.metadata[package_name].get('manual', False'):
                self._build_package(package_path)
            
            print(f"✅ {package_name} successfully updated")
        except GitCommandError as e:
            print(f"❌ Update error: {str(e)}")

    def reinstall(self, package_name, manual=False):
        """Reinstall existing package"""
        if package_name not in self.metadata:
            print(f"❌ Package {package_name} not found")
            return
            
        metadata = self.metadata[package_name]
        self.install(
            metadata['url'],
            source=metadata.get('source', 'main'),
            manual=manual or metadata.get('manual', False),
            reinstall=True
        )

    def _extract_name(self, repo_url):
        """Extract package name from repository URL"""
        return repo_url.split('/')[-1].replace('.git', '')

def main():
    parser = argparse.ArgumentParser(description='Gitstaller - Git-based package manager')
    subparsers = parser.add_subparsers(dest='command')

    # Install command
    install_parser = subparsers.add_parser('install', help='Install a package')
    install_parser.add_argument('repo_url', help='Git repository URL')
    install_parser.add_argument('-m', '--manual', action='store_true', 
                              help='Skip automatic build')
    install_parser.add_argument('--source', choices=['main', 'latest-release', 'version'],
                              default='main', help='Installation source')
    install_parser.add_argument('--version', help='Specific version to install')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update a package')
    update_parser.add_argument('package_name', help='Installed package name')
    update_parser.add_argument('-m', '--manual', action='store_true',
                             help='Skip build during update')

    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a package')
    remove_parser.add_argument('package_name', help='Installed package name')

    # Reinstall command
    reinstall_parser = subparsers.add_parser('reinstall', help='Reinstall a package')
    reinstall_parser.add_argument('package_name', help='Installed package name')
    reinstall_parser.add_argument('-m', '--manual', action='store_true',
                                help='Skip build during reinstall')

    args = parser.parse_args()
    gitstaller = Gitstaller()

    try:
        if args.command == 'install':
            source_spec = args.source
            if args.source == 'version' and not args.version:
                raise ValueError("--version required when using 'version' source")
            if args.version:
                source_spec = args.version
            gitstaller.install(args.repo_url, source=source_spec, manual=args.manual)
        
        elif args.command == 'update':
            gitstaller.update(args.package_name, manual=args.manual)
        
        elif args.command == 'remove':
            gitstaller.remove(args.package_name)
        
        elif args.command == 'reinstall':
            gitstaller.reinstall(args.package_name, manual=args.manual)
        
        else:
            parser.print_help()
    
    except ValueError as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
