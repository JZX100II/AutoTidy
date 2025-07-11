import os
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk
from disk_broom import (
    validate_directory_path, confirm_action, format_file_size, analyze_files,
    clean_user_and_browser_caches, empty_trash_directory, clean_system_packages_and_logs
)
from datetime import datetime
import sys
import io
import threading

class DiskBroomWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="DiskBroom - GTK")
        self.set_default_size(800, 600)
        self.set_border_width(10)

        # Main vertical box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_box)

        # Notebook for tabs
        notebook = Gtk.Notebook()
        notebook.set_margin_top(10)
        notebook.set_margin_bottom(10)
        main_box.pack_start(notebook, True, True, 0)

        # Analyze Files Tab
        analyze_tab = self.create_analyze_tab()
        notebook.append_page(analyze_tab, Gtk.Label(label="Analyze Files"))

        # Clean Caches Tab
        cache_tab = self.create_cache_tab()
        notebook.append_page(cache_tab, Gtk.Label(label="Clean Caches"))

        # Empty Trash Tab
        trash_tab = self.create_trash_tab()
        notebook.append_page(trash_tab, Gtk.Label(label="Empty Trash"))

        # System Cleanup Tab
        system_tab = self.create_system_tab()
        notebook.append_page(system_tab, Gtk.Label(label="System Cleanup"))

    def create_analyze_tab(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)

        # Directory selection
        dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        dir_label = Gtk.Label(label="Directory:")
        dir_box.pack_start(dir_label, False, False, 0)
        self.dir_entry = Gtk.Entry()
        self.dir_entry.set_hexpand(True)
        dir_box.pack_start(self.dir_entry, True, True, 0)
        dir_button = Gtk.Button(label="Browse")
        dir_button.connect("clicked", self.on_dir_button_clicked)
        dir_box.pack_start(dir_button, False, False, 0)
        main_box.pack_start(dir_box, False, False, 0)

        # Options
        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        options_box.set_halign(Gtk.Align.CENTER)
        self.find_duplicates = Gtk.CheckButton(label="Find Duplicates")
        options_box.pack_start(self.find_duplicates, False, False, 10)
        self.find_old = Gtk.CheckButton(label="Find Old Files")
        options_box.pack_start(self.find_old, False, False, 10)
        self.find_oversized = Gtk.CheckButton(label="Find Oversized Files")
        options_box.pack_start(self.find_oversized, False, False, 10)
        self.find_junk = Gtk.CheckButton(label="Find Junk Files")
        options_box.pack_start(self.find_junk, False, False, 10)
        main_box.pack_start(options_box, False, False, 0)

        # Parameters
        params_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        params_box.set_halign(Gtk.Align.CENTER)

        min_size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        min_size_label = Gtk.Label(label="Min Duplicate Size (KB):")
        min_size_box.pack_start(min_size_label, False, False, 0)
        self.min_size_entry = Gtk.Entry(text="10")
        self.min_size_entry.set_width_chars(6)
        min_size_box.pack_start(self.min_size_entry, False, False, 0)
        params_box.pack_start(min_size_box, False, False, 10)

        months_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        months_label = Gtk.Label(label="Stale Months:")
        months_box.pack_start(months_label, False, False, 0)
        self.months_entry = Gtk.Entry(text="6")
        self.months_entry.set_width_chars(6)
        months_box.pack_start(self.months_entry, False, False, 0)
        params_box.pack_start(months_box, False, False, 10)

        large_size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        large_size_label = Gtk.Label(label="Large File Size (MB):")
        large_size_box.pack_start(large_size_label, False, False, 0)
        self.large_size_entry = Gtk.Entry(text="1024")
        self.large_size_entry.set_width_chars(6)
        large_size_box.pack_start(self.large_size_entry, False, False, 0)
        params_box.pack_start(large_size_box, False, False, 10)

        stale_secs_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        stale_secs_label = Gtk.Label(label="Stale Download Secs:")
        stale_secs_box.pack_start(stale_secs_label, False, False, 0)
        self.stale_secs_entry = Gtk.Entry(text="3600")
        self.stale_secs_entry.set_width_chars(6)
        stale_secs_box.pack_start(self.stale_secs_entry, False, False, 0)
        params_box.pack_start(stale_secs_box, False, False, 10)

        main_box.pack_start(params_box, False, False, 0)

        # Dry run
        self.dry_run = Gtk.CheckButton(label="Dry Run")
        self.dry_run.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(self.dry_run, False, False, 0)

        # Analyze button and spinner
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        self.analyze_button = Gtk.Button(label="Analyze")
        self.analyze_button.connect("clicked", self.on_analyze_clicked)
        button_box.pack_start(self.analyze_button, False, False, 0)
        self.analyze_spinner = Gtk.Spinner()
        self.analyze_spinner.get_style_context().add_class("spinner")
        button_box.pack_start(self.analyze_spinner, False, False, 10)
        main_box.pack_start(button_box, False, False, 10)

        # Results
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.results_text = Gtk.TextView()
        self.results_text.set_editable(False)
        self.results_text.set_monospace(True)
        scrolled.add(self.results_text)
        main_box.pack_start(scrolled, True, True, 0)

        return main_box

    def create_cache_tab(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)

        self.cache_dry_run = Gtk.CheckButton(label="Dry Run")
        self.cache_dry_run.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(self.cache_dry_run, False, False, 0)

        # Clean button and spinner
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        self.cache_button = Gtk.Button(label="Clean User and Browser Caches")
        self.cache_button.connect("clicked", self.on_clean_caches_clicked)
        button_box.pack_start(self.cache_button, False, False, 0)
        self.cache_spinner = Gtk.Spinner()
        self.cache_spinner.get_style_context().add_class("spinner")
        button_box.pack_start(self.cache_spinner, False, False, 10)
        main_box.pack_start(button_box, False, False, 10)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.cache_results = Gtk.TextView()
        self.cache_results.set_editable(False)
        self.cache_results.set_monospace(True)
        scrolled.add(self.cache_results)
        main_box.pack_start(scrolled, True, True, 0)

        return main_box

    def create_trash_tab(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)

        self.trash_dry_run = Gtk.CheckButton(label="Dry Run")
        self.trash_dry_run.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(self.trash_dry_run, False, False, 0)

        # Trash button and spinner
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        self.trash_button = Gtk.Button(label="Empty Trash")
        self.trash_button.connect("clicked", self.on_empty_trash_clicked)
        button_box.pack_start(self.trash_button, False, False, 0)
        self.trash_spinner = Gtk.Spinner()
        self.trash_spinner.get_style_context().add_class("spinner")
        button_box.pack_start(self.trash_spinner, False, False, 10)
        main_box.pack_start(button_box, False, False, 10)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.trash_results = Gtk.TextView()
        self.trash_results.set_editable(False)
        self.trash_results.set_monospace(True)
        scrolled.add(self.trash_results)
        main_box.pack_start(scrolled, True, True, 0)

        return main_box

    def create_system_tab(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)

        # System button and spinner
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        self.system_button = Gtk.Button(label="Clean System Packages and Logs")
        self.system_button.connect("clicked", self.on_clean_system_clicked)
        button_box.pack_start(self.system_button, False, False, 0)
        self.system_spinner = Gtk.Spinner()
        self.system_spinner.get_style_context().add_class("spinner")
        button_box.pack_start(self.system_spinner, False, False, 10)
        main_box.pack_start(button_box, False, False, 10)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.system_results = Gtk.TextView()
        self.system_results.set_editable(False)
        self.system_results.set_monospace(True)
        scrolled.add(self.system_results)
        main_box.pack_start(scrolled, True, True, 0)

        return main_box

    def on_dir_button_clicked(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select Directory", parent=self, action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.dir_entry.set_text(dialog.get_filename())
        dialog.destroy()

    def on_analyze_clicked(self, button):
        directory = self.dir_entry.get_text()
        if not validate_directory_path(directory):
            self.show_message("Invalid directory path")
            self.dir_entry.get_style_context().add_class("error")
            return
        else:
            self.dir_entry.get_style_context().remove_class("error")

        try:
            min_size = int(self.min_size_entry.get_text()) * 1024
            months = int(self.months_entry.get_text())
            large_size = int(self.large_size_entry.get_text()) * 1024 * 1024
            stale_secs = int(self.stale_secs_entry.get_text())
        except ValueError:
            self.show_message("Invalid input for parameters")
            self.min_size_entry.get_style_context().add_class("error")
            self.months_entry.get_style_context().add_class("error")
            self.large_size_entry.get_style_context().add_class("error")
            self.stale_secs_entry.get_style_context().add_class("error")
            return
        else:
            self.min_size_entry.get_style_context().remove_class("error")
            self.months_entry.get_style_context().remove_class("error")
            self.large_size_entry.get_style_context().remove_class("error")
            self.stale_secs_entry.get_style_context().remove_class("error")

        self.dry_run.set_sensitive(False)
        self.analyze_button.set_sensitive(False)
        self.analyze_spinner.start()
        self.analyze_spinner.show()

        def analyze_task():
            output = io.StringIO()
            try:
                oversized_files, old_files, junk_files, duplicates, scan_errors = analyze_files(
                    directory, min_size, months, large_size, stale_secs
                )

                output.write(f"Analysis Results for {directory}\n")
                output.write("=" * 80 + "\n\n")

                if self.find_oversized.get_active() and oversized_files:
                    output.write(f"Oversized Files (>{format_file_size(large_size)}):\n")
                    output.write("-" * 80 + "\n")
                    for path, size in oversized_files:
                        output.write(f"Path: {path}\nSize: {format_file_size(size)}\n\n")

                if self.find_old.get_active() and old_files:
                    output.write(f"Old Files (Not touched in {months} months):\n")
                    output.write("-" * 80 + "\n")
                    for path, atime, mtime in old_files:
                        output.write(f"Path: {path}\n")
                        output.write(f"Last Accessed: {datetime.fromtimestamp(atime).strftime('%Y-%m-%d')}\n")
                        output.write(f"Last Modified: {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')}\n\n")

                if self.find_duplicates.get_active() and duplicates:
                    output.write(f"Found {len(duplicates)} sets of duplicates:\n")
                    output.write("-" * 80 + "\n")
                    for file_hash, paths in duplicates.items():
                        output.write(f"Duplicate Hash: {file_hash}\n")
                        for path in paths:
                            size = format_file_size(os.path.getsize(path)) if os.path.exists(path) else "?"
                            output.write(f"Path: {path}\nSize: {size}\n")
                        output.write("\n")

                if self.find_junk.get_active() and junk_files:
                    output.write("Junk Files:\n")
                    output.write("-" * 80 + "\n")
                    for path, reason in junk_files:
                        output.write(f"Path: {path}\nReason: {reason}\n\n")

                if scan_errors:
                    output.write(f"Encountered {len(scan_errors)} errors during analysis.\n")

                GLib.idle_add(self.update_analyze_results, output.getvalue())
            finally:
                output.close()
                GLib.idle_add(self.finish_analyze)

        threading.Thread(target=analyze_task, daemon=True).start()

    def update_analyze_results(self, text):
        buffer = self.results_text.get_buffer()
        buffer.set_text(text)
        return False

    def finish_analyze(self):
        self.analyze_spinner.stop()
        self.analyze_spinner.hide()
        self.analyze_button.set_sensitive(True)
        self.dry_run.set_sensitive(True)
        return False

    def on_clean_caches_clicked(self, button):
        if not self.show_confirm("Clean user and browser caches?"):
            return

        self.cache_button.set_sensitive(False)
        self.cache_dry_run.set_sensitive(False)
        self.cache_spinner.start()
        self.cache_spinner.show()

        def clean_caches_task():
            output = io.StringIO()
            try:
                result = clean_user_and_browser_caches(self.cache_dry_run.get_active())
                output.write("Cache Cleaning Results:\n")
                output.write("=" * 80 + "\n\n")
                output.write(str(result) + "\n")
                GLib.idle_add(self.update_cache_results, output.getvalue())
            finally:
                output.close()
                GLib.idle_add(self.finish_cache_clean)

        threading.Thread(target=clean_caches_task, daemon=True).start()

    def update_cache_results(self, text):
        buffer = self.cache_results.get_buffer()
        buffer.set_text(text)
        return False

    def finish_cache_clean(self):
        self.cache_spinner.stop()
        self.cache_spinner.hide()
        self.cache_button.set_sensitive(True)
        self.cache_dry_run.set_sensitive(True)
        return False

    def on_empty_trash_clicked(self, button):
        if not self.show_confirm("Empty system trash?"):
            return

        self.trash_button.set_sensitive(False)
        self.trash_dry_run.set_sensitive(False)
        self.trash_spinner.start()
        self.trash_spinner.show()

        def empty_trash_task():
            output = io.StringIO()
            try:
                result = empty_trash_directory(self.trash_dry_run.get_active())
                output.write("Trash Emptying Results:\n")
                output.write("=" * 80 + "\n\n")
                output.write(str(result) + "\n")
                GLib.idle_add(self.update_trash_results, output.getvalue())
            finally:
                output.close()
                GLib.idle_add(self.finish_trash_empty)

        threading.Thread(target=empty_trash_task, daemon=True).start()

    def update_trash_results(self, text):
        buffer = self.trash_results.get_buffer()
        buffer.set_text(text)
        return False

    def finish_trash_empty(self):
        self.trash_spinner.stop()
        self.trash_spinner.hide()
        self.trash_button.set_sensitive(True)
        self.trash_dry_run.set_sensitive(True)
        return False

    def on_clean_system_clicked(self, button):
        if not self.show_confirm("Clean system packages and logs?"):
            return

        self.system_button.set_sensitive(False)
        self.system_spinner.start()
        self.system_spinner.show()

        def clean_system_task():
            output = io.StringIO()
            try:
                result = clean_system_packages_and_logs()
                output.write("System Cleanup Results:\n")
                output.write("=" * 80 + "\n\n")
                output.write(str(result) + "\n")
                GLib.idle_add(self.update_system_results, output.getvalue())
            finally:
                output.close()
                GLib.idle_add(self.finish_system_clean)

        threading.Thread(target=clean_system_task, daemon=True).start()

    def update_system_results(self, text):
        buffer = self.system_results.get_buffer()
        buffer.set_text(text)
        return False

    def finish_system_clean(self):
        self.system_spinner.stop()
        self.system_spinner.hide()
        self.system_button.set_sensitive(True)
        return False

    def show_message(self, message):
        dialog = Gtk.MessageDialog(
            parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=message
        )
        dialog.run()
        dialog.destroy()

    def show_confirm(self, message):
        dialog = Gtk.MessageDialog(
            parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=message
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

def main():
    # Add CSS for error styling and spinner
    css = b"""
    .error {
        border: 2px solid red;
    }
    .spinner {
        padding: 6px;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    win = DiskBroomWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()