import os
import time
import hashlib
import logging
import argparse
import subprocess
from pathlib import Path
from rich.table import Table
from datetime import datetime
from rich.progress import track
from rich.console import Console
from collections import defaultdict

console = Console()

# Setup logging
logging.basicConfig(
    filename="diskbroom.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def validate_directory_path(path):
    """Validate that the path is a string, exists, and is a directory."""
    if path is None:
        console.print("[red]❌ Directory path cannot be None.[/red]")
        return False
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        console.print(f"[red]❌ Directory {path} does not exist.[/red]")
        return False
    if not os.path.isdir(path):
        console.print(f"[red]❌ Path {path} is not a directory.[/red]")
        return False
    return path

def confirm_action(prompt):
    """Prompt user for confirmation (y/N)."""
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer == "y"

def execute_system_command(cmd):
    """Run a shell command and log errors."""
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logging.info(f"Executed command: {' '.join(cmd)}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Command failed: {' '.join(cmd)} - {e.stderr}[/red]")
        logging.error(f"Command failed: {' '.join(cmd)} - {e.stderr}")
        return False
    return True

def format_file_size(size):
    """Format file size in human-readable units."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def compute_file_hash(path, block_size=65536, sample=False):
    """Compute SHA-256 hash of file contents, optionally sampling first 1MB."""
    hasher = hashlib.sha256()  # Use SHA-256 for better collision resistance
    try:
        with open(path, 'rb') as f:
            if sample:
                hasher.update(f.read(1024 * 1024))  # Sample first 1MB
            else:
                for block in iter(lambda: f.read(block_size), b''):
                    hasher.update(block)
        return hasher.hexdigest()
    except Exception as e:
        console.print(f"[red]❌ Error reading {path}: {e}[/red]")
        logging.error(f"Error reading {path}: {e}")
        return None

def get_file_attributes(file_path, months=6, oversized_threshold=1024*1024*1024, download_stale_secs=3600):
    """Get file attributes (size, staleness, last access/modified times)."""
    try:
        file_stat = os.stat(file_path)
        size = file_stat.st_size
        is_oversized = size > oversized_threshold
        last_access = file_stat.st_atime
        last_mod = file_stat.st_mtime
        threshold = time.time() - (months * 30 * 24 * 3600)
        is_old = last_access < threshold and last_mod < threshold
        is_stale_download = (time.time() - last_mod) > download_stale_secs if file_path.endswith(('.crdownload', '.part')) else False
        return {
            'size': size,
            'is_oversized': is_oversized,
            'is_old': is_old,
            'is_stale_download': is_stale_download,
            'last_access': last_access,
            'last_mod': last_mod
        }
    except Exception as e:
        console.print(f"[red]❌ Error accessing {file_path}: {e}[/red]")
        logging.error(f"Error accessing {file_path}: {e}")
        return None

def display_results_table(title, data, columns, header_style):
    """Display a table of cleanup results with dynamic columns."""
    table = Table(title=title, header_style=header_style)
    for col, width in columns:
        table.add_column(col, width=width, overflow="fold")
    for row in data:
        table.add_row(*row)
    console.print(table)

def clean_system_packages_and_logs():
    """Clean APT packages and system logs."""
    console.rule("[bold red]🧹 Running System Package and Log Cleanup")
    if not confirm_action("⚠️ This will run 'sudo apt clean', 'journalctl --vacuum', etc. Continue?"):
        console.print("[cyan]❎ Cancelled system cleanup.[/cyan]")
        return

    commands = [
        ["sudo", "apt", "autoremove", "-y"],
        ["sudo", "apt", "autoclean"],
        ["sudo", "apt", "clean"],
        ["sudo", "journalctl", "--vacuum-time=7d"],
    ]

    for cmd in commands:
        console.print(f"[yellow]→ Running:[/yellow] {' '.join(cmd)}")
        execute_system_command(cmd)

def empty_trash_directory(dry_run=False):
    """Empty the system trash directory."""
    trash_path = os.path.expanduser("~/.local/share/Trash/files")
    if not os.path.exists(trash_path):
        console.print("[yellow]⚠️ Trash directory does not exist.[/yellow]")
        return

    files_to_delete = []
    for root, _, files in os.walk(trash_path, topdown=False):
        for name in files:
            files_to_delete.append(os.path.join(root, name))

    if not files_to_delete:
        console.print("[green]✅ Trash directory is empty.[/green]")
        return

    if dry_run:
        console.print("[cyan]🗑️ Dry run: Would delete {} files from trash.[/cyan]".format(len(files_to_delete)))
        return

    if confirm_action(f"⚠️ Delete {len(files_to_delete)} files from trash?"):
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                logging.info(f"Deleted trash file: {file_path}")
            except Exception as e:
                console.print(f"[red]❌ Could not delete {file_path}: {e}[/red]")
                logging.error(f"Could not delete {file_path}: {e}")
        console.print("[green]🧺 Emptied system trash folder[/green]")

def analyze_files(root, min_duplicate_size=0, months=6, oversized_threshold=1024*1024*1024, download_stale_secs=3600):
    """Analyze files for oversized, old, duplicate, and junk files in one pass."""
    root = validate_directory_path(root)
    if not root:
        return [], [], [], []

    junk_file_patterns = {
        'ext': {'.old', '.part', '.crdownload', '.trash'},
        'prefix': {'unconfirmed', 'trash', 'core'},
        'suffix': {'.crdownload', '.part', 'trash'},
        'exact': {'.trash', '.trash-1000'}
    }

    oversized_files = []
    old_files = []
    junk_files = []
    file_hashes = defaultdict(list)
    scan_errors = []

    for dirpath, _, filenames in track(os.walk(root), description="🔍 Analyzing files..."):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            name_lower = filename.lower()
            ext = os.path.splitext(filename)[1].lower()

            # Get file attributes
            attributes = get_file_attributes(full_path, months, oversized_threshold, download_stale_secs)
            if not attributes:
                scan_errors.append(f"Error accessing {full_path}")
                continue

            # Check for oversized files
            if attributes['is_oversized']:
                oversized_files.append((full_path, attributes['size']))

            # Check for old files
            if attributes['is_old']:
                old_files.append((full_path, attributes['last_access'], attributes['last_mod']))

            # Check for junk files
            if attributes['size'] == 0:
                junk_files.append((full_path, 'Empty File'))
            elif (
                ext in junk_file_patterns['ext'] or
                any(name_lower.startswith(pfx) for pfx in junk_file_patterns['prefix']) or
                any(name_lower.endswith(sfx) for sfx in junk_file_patterns['suffix']) or
                name_lower in junk_file_patterns['exact'] or
                attributes['is_stale_download']
            ):
                junk_files.append((full_path, 'Temporary File' if not attributes['is_stale_download'] else 'Stale Incomplete Download'))

            # Check for duplicates
            if attributes['size'] >= min_duplicate_size:
                file_hash = compute_file_hash(full_path, sample=attributes['size'] > 10*1024*1024)  # Sample for files > 10MB
                if file_hash:
                    file_hashes[file_hash].append(full_path)

    duplicates = {h: paths for h, paths in file_hashes.items() if len(paths) > 1}
    return oversized_files, old_files, junk_files, duplicates, scan_errors

def clean_user_and_browser_caches(dry_run=False):
    """Clean user and browser cache directories with age threshold."""
    directories = [
        ("~/.cache/thumbnails", 0)
    ]

    browser_cache_patterns = [
        ".mozilla/firefox/*/cache2",
        ".config/google-chrome/Default/Cache",
        ".config/chromium/Default/Cache",
        ".config/microsoft-edge/Default/Cache",
        ".config/BraveSoftware/Brave-Browser/Default/Cache",
    ]

    users = [str(path) for path in Path("/home").iterdir() if path.is_dir()]
    for user_home in users:
        directories.extend([
            # Not sure about all of these
            (f"{user_home}/.cache/pip", 30),
            (f"{user_home}/.npm", 30),
            (f"{user_home}/.composer/cache", 30),
            (f"{user_home}/.cache", 30),
            (f"{user_home}/.local/share/Trash", 0),
            (f"{user_home}/.thumbnails", 30),
        ])
        for pattern in browser_cache_patterns:
            for path in Path(user_home).rglob(pattern):
                directories.append((str(path), 0))

    files_to_delete = []
    for dir_path, days in directories:
        abs_path = os.path.expanduser(dir_path)
        if os.path.exists(abs_path):
            for root, _, files in os.walk(abs_path):
                for name in files:
                    full_path = os.path.join(root, name)
                    try:
                        if days == 0 or (time.time() - os.path.getmtime(full_path)) > days * 86400:
                            files_to_delete.append(full_path)
                    except Exception:
                        continue

    if not files_to_delete:
        console.print("[green]✅ No cache files to clean.[/green]")
        return

    if dry_run:
        console.print("[cyan]🧹 Dry run: Would delete {} cache files.[/cyan]".format(len(files_to_delete)))
        return

    if confirm_action(f"⚠️ Delete {len(files_to_delete)} cache files?"):
        cleaned = 0
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                logging.info(f"Deleted cache file: {file_path}")
                cleaned += 1
            except Exception as e:
                console.print(f"[red]❌ Could not delete {file_path}: {e}[/red]")
                logging.error(f"Could not delete {file_path}: {e}")
        console.print(f"[cyan]🧹 Cleaned {cleaned} cache files.[/cyan]")

def main():
    """Main function to parse arguments and run disk cleanup tasks."""
    parser = argparse.ArgumentParser(description="🔍 DiskBroom CLI Tool for Linux disk cleanup")
    parser.add_argument("--directory", type=str, help="Target directory to analyze")
    parser.add_argument("--find-duplicates", action="store_true", help="Find duplicate files")
    parser.add_argument("--find-old-files", action="store_true", help="Find files not accessed or modified in months")
    parser.add_argument("--find-oversized-files", action="store_true", help="Find files exceeding size threshold")
    parser.add_argument("--find-junk-files", action="store_true", help="Find temporary or incomplete download files")
    parser.add_argument("--clean-user-and-browser-caches", action="store_true", help="Clean user and browser cache directories")
    parser.add_argument("--clean-system-packages-and-logs", action="store_true", help="Clean APT packages and system logs")
    parser.add_argument("--empty-trash", action="store_true", help="Empty system trash directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without deleting")
    parser.add_argument("--min-duplicate-size", type=int, default=10*1024, help="Minimum file size for duplicate check (bytes)")
    parser.add_argument("--stale-months", type=int, default=6, help="Months threshold for old file check")
    parser.add_argument("--large-file-size", type=int, default=1024*1024*1024, help="Threshold for oversized file size (bytes)")
    parser.add_argument("--download-stale-secs", type=int, default=3600, help="Stale download threshold (seconds)")

    args = parser.parse_args()

    # Validate directory for analysis operations
    if any([args.find_old_files, args.find_oversized_files, args.find_duplicates, args.find_junk_files]):
        if not validate_directory_path(args.directory):
            return

    # Analyze files once for all checks
    if any([args.find_old_files, args.find_oversized_files, args.find_duplicates, args.find_junk_files]):
        oversized_files, old_files, junk_files, duplicates, scan_errors = analyze_files(
            args.directory, args.min_duplicate_size, args.stale_months, args.large_file_size, args.download_stale_secs
        )

        # Display results
        if args.find_oversized_files and oversized_files:
            display_results_table(
                f"📦 Oversized Files (>{format_file_size(args.large_file_size)})",
                [(path, format_file_size(size)) for path, size in oversized_files],
                [("Path", 60), ("Size", 10)],
                "bold red"
            )

        if args.find_old_files and old_files:
            display_results_table(
                f"🕒 Old Files (Not touched in {args.stale_months} months)",
                [(path, datetime.fromtimestamp(atime).strftime('%Y-%m-%d'), datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')) for path, atime, mtime in old_files],
                [("Path", 60), ("Last Accessed", 15), ("Last Modified", 15)],
                "bold magenta"
            )

        if args.find_duplicates and duplicates:
            console.print(f"[yellow]🗂️ Found {len(duplicates)} sets of duplicates:[/yellow]")
            for file_hash, paths in duplicates.items():
                console.rule(f"🔁 [bold yellow]Duplicate Hash[/bold yellow]: {file_hash}")
                display_results_table(
                    "Duplicate Files",
                    [(path, format_file_size(os.path.getsize(path)) if os.path.exists(path) else "?") for path in paths],
                    [("Path", 60), ("Size", 10)],
                    "bold blue"
                )

        if args.find_junk_files and junk_files:
            display_results_table(
                "🗑️ Junk Files",
                [(path, reason) for path, reason in junk_files],
                [("Path", 60), ("Reason", 20)],
                "bold red"
            )

        if scan_errors:
            console.print(f"[red]⚠️ Encountered {len(scan_errors)} errors during analysis.[/red]")
            logging.error(f"Analysis errors: {scan_errors}")

    # Perform cleanup operations
    if args.empty_trash:
        empty_trash_directory(args.dry_run)

    if args.clean_user_and_browser_caches:
        clean_user_and_browser_caches(args.dry_run)

    if args.clean_system_packages_and_logs:
        clean_system_packages_and_logs()

if __name__ == "__main__":
    main()