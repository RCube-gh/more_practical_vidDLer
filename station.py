import os
import sys
import re
import asyncio
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, Container
from textual.widgets import Header, Footer, Input, Log, Static, Label, Button, DataTable
from textual.screen import ModalScreen
from textual.reactive import reactive
from rich.text import Text

# --- Configuration ---
DOWNLOAD_DIR = Path("/app/downloads")
SAFE_DIR = Path("/app/safe_output")

# Fixed safe limit for stability (ffmpeg is heavy!)
MAX_CONCURRENT_TASKS = 3
task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

# --- Logic ---

class Downloader:
    def __init__(self, logger_func):
        self.log = logger_func

    async def run_pipeline(self, url: str, progress_callback) -> str:
        async with task_semaphore:
            self.log(f"[Start] Extraction: {url}")
            raw_file = await self.download(url, progress_callback)
            
            if not raw_file:
                self.log(f"[Failed] Extraction failed: {url}")
                return None

            self.log(f"[DL Done] {raw_file.name}")
            progress_callback(0, "download_done", "Prep...")

            self.log(f"[Start] Sanitization: {raw_file.name}")
            clean_file = await self.sanitize(raw_file, progress_callback)

            if clean_file:
                # Stats Calculation
                try:
                    raw_size = raw_file.stat().st_size
                    clean_size = clean_file.stat().st_size
                    diff = raw_size - clean_size
                    percent = (abs(diff) / raw_size) * 100 if raw_size > 0 else 0
                    
                    def fmt(s):
                        for unit in ['B', 'KB', 'MB', 'GB']:
                            if s < 1024: return f"{s:.2f}{unit}"
                            s /= 1024
                        return f"{s:.2f}TB"

                    if diff > 0:
                        self.log(f"[Diet] {fmt(raw_size)} -> {fmt(clean_size)} (Saved {fmt(diff)}, {percent:.1f}%)")
                    else:
                        self.log(f"[Gain] {fmt(raw_size)} -> {fmt(clean_size)} (Increased {fmt(abs(diff))}, {percent:.1f}%)")
                except: pass

                self.log(f"[Complete] Cleaned: {clean_file.name}")
                try: os.remove(raw_file)
                except: pass
                return clean_file
            else:
                self.log(f"💀 [Failed] Sanitization died: {raw_file.name}")
                return None

    async def download(self, url: str, progress_callback):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        template = str(DOWNLOAD_DIR / f"%(title)s_{timestamp}.%(ext)s")
        cmd = ["yt-dlp", "--newline", "--no-playlist", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "-o", template, url]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

        final_filename = None
        stats_pattern = re.compile(r"\[download\]\s+(\d+\.?\d*)%.*at\s+(\S+)\s+ETA\s+(\S+)")
        f_pattern = re.compile(r"\[download\] Destination: (.+)")
        f_merge = re.compile(r"\[Merger\] Merging formats into \"(.+)\"")
        f_exist = re.compile(r"\[download\] (.+) has already been downloaded")

        while True:
            line = await process.stdout.readline()
            if not line: break
            text = line.decode('utf-8', errors='replace').strip()
            
            detected_name = None
            if f_pattern.search(text): detected_name = f_pattern.search(text).group(1)
            if f_merge.search(text): detected_name = f_merge.search(text).group(1)
            if f_exist.search(text): detected_name = f_exist.search(text).group(1)
            
            if detected_name:
                final_filename = detected_name
                try:
                    name_clean = Path(detected_name).stem
                    if re.search(r'\.f\d+$', name_clean): name_clean = Path(name_clean).stem
                    name_clean = re.sub(r'\s*\[.*?\]$', '', name_clean)
                    progress_callback(None, "title", name_clean)
                except: pass

            if "Sleeping" in text: progress_callback(None, "download", "💤 Wait...")
            if "[Merger]" in text: progress_callback(None, "download", "🧩 Merging...")

            match = stats_pattern.search(text)
            if match:
                p, s, e = float(match.group(1)), match.group(2), match.group(3)
                progress_callback(p, "download", f"{s} | ETA {e}")
            elif "[download]" in text and "%" in text:
                 p_match = re.search(r"(\d+\.?\d*)%", text)
                 if p_match: progress_callback(float(p_match.group(1)), "download", "")

        await process.wait()
        return Path(final_filename) if (process.returncode == 0 and final_filename) else None

    async def sanitize(self, input_path: Path, progress_callback):
        # Relaxed Sanitization: Only replace filesystem unsafe chars to keep Japanese
        # Unsafe: < > : " / \ | ? *
        safe_stem = re.sub(r'[<>:"/\\|?*]', '_', input_path.stem)
        # Remove non-printable chars just in case
        safe_stem = "".join(c for c in safe_stem if c.isprintable())
        
        safe_name = safe_stem + "_clean.mp4"
        output_path = SAFE_DIR / safe_name
        
        # Collision Avoidance
        counter = 1
        while output_path.exists():
            output_path = SAFE_DIR / f"{safe_stem}_clean_{counter}.mp4"
            counter += 1

        duration = await self.get_duration(input_path)
        
        cmd = ['ffmpeg', '-y', '-nostdin', '-i', str(input_path), '-map', '0:v:0', '-map', '0:a:0?', '-map_metadata', '-1', '-map_chapters', '-1', '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-c:a', 'aac', str(output_path)]
        process = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)

        time_pattern = re.compile(r"time=(\d+:\d+:\d+\.\d+)")
        speed_pattern = re.compile(r"speed=\s*(\S+)")
        buffer = bytearray()

        start_time = datetime.now()
        
        while True:
            try: chunk = await process.stderr.read(128)
            except: break
            if not chunk: break
            buffer.extend(chunk)
            while True:
                idx_r = buffer.find(b'\r')
                idx_n = buffer.find(b'\n')
                idx = min(i for i in [idx_r, idx_n] if i != -1) if (idx_r!=-1 or idx_n!=-1) else -1
                if idx == -1: break
                line, buffer = buffer[:idx], buffer[idx+1:]
                text = line.decode('utf-8', errors='ignore').strip()
                
                t_match = time_pattern.search(text)
                if t_match and duration:
                    cur_time_str = t_match.group(1).split('.')[0]
                    sp_match = speed_pattern.search(text)
                    speed_str = sp_match.group(1) if sp_match else "?x"
                    h, m, s = cur_time_str.split(':')
                    curr = int(h)*3600 + int(m)*60 + int(s)
                    pct = min((curr / duration) * 100, 99.9)
                    
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > 0 and pct > 0:
                        total_estimated = elapsed * (100 / pct)
                        remaining = total_estimated - elapsed
                        eta_min, eta_sec = divmod(int(remaining), 60)
                        eta_str = f"{eta_min:02d}:{eta_sec:02d}"
                    else:
                        eta_str = "--:--"
                    
                    progress_callback(pct, "sanitize", f"{cur_time_str} | {speed_str} | ETA {eta_str}")

        await process.wait()
        return output_path if process.returncode == 0 else None

    async def get_duration(self, input_path: Path):
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(input_path)]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await proc.communicate()
            return float(out.decode().strip())
        except: return None

# --- UI Components ---

class ConfirmExitScreen(ModalScreen):
    CSS = """
    ConfirmExitScreen { align: center middle; background: rgba(0,0,0,0.7); }
    #dialog { padding: 1 2; background: #1f2335; border: wide #f7768e; height: auto; width: 50; }
    #dialog Label { width: 100%; content-align: center middle; margin-bottom: 2; color: #c0caf5; }
    #dialog Horizontal { width: 100%; height: auto; align: center middle; }
    Button { margin: 0 2; }
    """
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("⚠️ Are you sure you want to abort all active tasks? ⚠️")
            with Horizontal():
                yield Button("Cancel", id="cancel", variant="primary")
                yield Button("ABORT", id="quit", variant="error")
    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "quit")

class StationApp(App):
    CSS = """
    Screen { background: #1a1b26; color: #a9b1d6; }
    #header { dock: top; height: 3; background: #7aa2f7; color: #1a1b26; content-align: center middle; text-style: bold; }
    #input-box { dock: top; height: 3; background: #16161e; padding: 0 1; border-bottom: solid #ff007c; }
    Input { width: 100%; background: #16161e; border: none; }
    #main-spliter { height: 1fr; }
    
    DataTable { 
        width: 60%; 
        height: 100%; 
        border-right: solid #565f89; 
        background: #1a1b26;
    }
    
    /* PREVENT CURSOR FROM KILLING COLORS */
    DataTable > .datatable--cursor {
        background: #3b4261;
        color: $text; /* Keep original colors, don't force white */
    }
    DataTable > .datatable--hover {
        background: #292e42;
        color: $text;
    }
    
    #right-col { width: 40%; height: 100%; background: #24283b; }
    Log { height: 100%; background: #24283b; }
    """

    active_tasks = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static(f"CleanStream Station", id="header")
        with Container(id="input-box"):
            yield Input(placeholder="URL (Ctrl+V)", id="url-input")
        with Horizontal(id="main-spliter"):
            yield DataTable(id="tasks-table")
            with Container(id="right-col"):
                yield Log(id="log", highlight=True)
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted):
        url = event.value.strip()
        if not url: return
        event.input.value = ""
        self.app.active_tasks += 1
        
        # Create a unique row key
        task_id = f"task_{datetime.now().timestamp()}"
        
        table = self.query_one(DataTable)
        # Initial Row: Title, Bar, Status
        # Use Text.from_markup to ensure colors are rendered!
        table.add_row(
            Text(f"{url}"), 
            self.generate_bar_text(0, "mode-dl"), 
            Text("Waiting..."), 
            key=task_id
        )
        
        # Scroll to the new row (bottom)
        row_index = table.row_count - 1
        table.move_cursor(row=row_index, animate=True)
        
        self.run_worker(self.process_task(url, task_id))

    def on_mount(self):
        self.query_one(Log).write_line(f"Ready. Concurrency Limit: {MAX_CONCURRENT_TASKS} tasks")
        table = self.query_one(DataTable)
        table.cursor_type = "none" # DISABLE SELECTION
        # Setup Columns with EXPLICIT KEYS
        table.add_column("Title", width=40, key="title")
        table.add_column("Progress", width=30, key="progress")
        table.add_column("Status", width=45, key="status")
        
        self.query_one("#url-input").focus()

    def generate_bar_text(self, percent, mode):
        BAR_WIDTH = 25
        filled = int(percent / 100 * BAR_WIDTH)
        empty = BAR_WIDTH - filled
        
        color = "white"
        if mode == "mode-dl": color = "#00ffff"      # Cyan
        elif mode == "mode-sanitize": color = "#9ece6a" # Bright Green
        elif mode == "completed": color = "#00ff00"     # Pure Green
        
        markup = f"[{color}]{'█' * filled}[/][dim white]{'░' * empty}[/]"
        return Text.from_markup(markup)

    async def process_task(self, url: str, task_id: str):
        downloader = Downloader(self.log_msg)
        table = self.query_one(DataTable)

        # State tracking for this task
        current_mode = "mode-dl"

        def cb(p, s, d=""): 
            nonlocal current_mode
            
            # Helper to update table safely
            try:
                # Update Title if changed
                if s == "title":
                    short_title = d if len(d) < 35 else d[:32] + "..."
                    # Use Text() to prevent brackets from triggering bad markup parsing
                    table.update_cell(task_id, "title", Text(f"{short_title}"))
                    return

                # Handle Phases
                if s == "download_done":
                    current_mode = "mode-sanitize"
                    table.update_cell(task_id, "progress", self.generate_bar_text(0, current_mode))
                    table.update_cell(task_id, "status", Text("Sanitizing..."))
                    return

                # Handle Progress Updates
                pct = p if p is not None else 0
                if s == "download" and current_mode == "mode-dl":
                    table.update_cell(task_id, "progress", self.generate_bar_text(pct, current_mode))
                    if p is not None:
                        table.update_cell(task_id, "status", Text(f"⬇️ {pct:.0f}% {d}"))
                    else:
                        table.update_cell(task_id, "status", Text(f"⬇️ {d}"))

                elif s == "sanitize" and current_mode == "mode-sanitize":
                    table.update_cell(task_id, "progress", self.generate_bar_text(pct, current_mode))
                    table.update_cell(task_id, "status", Text(f"{pct:.0f}% ({d})"))
            except: pass

        res = await downloader.run_pipeline(url, cb)
        
        # Finalize
        self.app.active_tasks -= 1
        if self.app.active_tasks < 0: self.app.active_tasks = 0
        
        try:
            if res:
                table.update_cell(task_id, "progress", self.generate_bar_text(100, "completed"))
                table.update_cell(task_id, "status", Text("Done"))
            else:
                table.update_cell(task_id, "status", Text("Error"))
        except: pass

    def log_msg(self, msg: str):
        t = datetime.now().strftime("%H:%M:%S")
        self.query_one(Log).write_line(f"[{t}] {msg}")

    def action_quit(self):
        def check_quit(should_quit: bool):
            if should_quit: self.exit()
        if self.active_tasks > 0:
            self.push_screen(ConfirmExitScreen(), check_quit)
        else:
            self.exit()

if __name__ == "__main__":
    StationApp().run()
