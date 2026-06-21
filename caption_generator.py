import os
import sys
import threading
import queue
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk, messagebox, colorchooser

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
IMAGEMAGICK_BINARY = r"C:\Program Files\ImageMagick-7.1.2-Q16\magick.exe"

import moviepy.config as cfg
if os.path.exists(IMAGEMAGICK_BINARY):
    cfg.change_settings({"IMAGEMAGICK_BINARY": IMAGEMAGICK_BINARY})

import whisper
from moviepy.editor import VideoFileClip, CompositeVideoClip, TextClip, ColorClip
from moviepy.video.tools.subtitles import SubtitlesClip
from proglog import ProgressBarLogger

class UiProgressLogger(ProgressBarLogger):
    def __init__(self, progress_fn, start_pct, end_pct):
        super().__init__()
        self.progress_fn = progress_fn
        self.start_pct = start_pct
        self.end_pct = end_pct
        self._last_pct_sent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        # Only react to actual progress updates (the running index),
        # not to 'total' being set or 'message' text changing - reacting
        # to those too was what made the percentage jump around / stick.
        if attr != "index":
            return
        total = self.bars[bar].get("total")
        if not total:
            return
        frac = max(0.0, min(1.0, value / total))
        pct = int(self.start_pct + frac * (self.end_pct - self.start_pct))
        # Throttle: only push an update when the integer percent actually changes,
        # to avoid flooding the UI thread's queue on long renders.
        if pct == self._last_pct_sent:
            return
        self._last_pct_sent = pct
        label = "Rendering video" if bar == "t" else "Writing audio"
        self.progress_fn(pct, f"{label}... ({int(frac * 100)}%)")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
class CaptionJob:
    def __init__(self, input_path, output_path, max_words, font_name, font_size,
                 font_color, stroke_color, stroke_width, bg_opacity, position,
                 model_name, log_fn, progress_fn):
        self.input_path = input_path
        self.output_path = output_path
        self.max_words = max_words
        self.font_name = font_name
        self.font_size = font_size
        self.font_color = font_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.bg_opacity = bg_opacity
        self.position = position
        self.model_name = model_name
        self.log = log_fn
        self.set_progress = progress_fn

    def run(self):
        self.set_progress(0, "Loading Whisper model...")
        self.log(f"Loading Whisper model '{self.model_name}'...")
        model = whisper.load_model(self.model_name)

        self.set_progress(10, "Transcribing audio...")
        self.log("Transcribing audio (this can take a while for long videos)...")
        result = model.transcribe(self.input_path)
        self.log(f"Transcription complete. {len(result['segments'])} segments found.")

        self.set_progress(45, "Building caption chunks...")
        subs = []
        for segment in result["segments"]:
            start = segment["start"]
            end = segment["end"]
            text = segment["text"].strip()
            if not text:
                continue
            words = text.split()
            duration = (end - start) / len(words)

            for i in range(0, len(words), self.max_words):
                chunk_words = words[i:i + self.max_words]
                chunk_text = " ".join(chunk_words)
                chunk_start = start + i * duration
                chunk_end = chunk_start + duration * len(chunk_words)
                subs.append(((chunk_start, chunk_end), chunk_text))

        self.set_progress(55, "Loading video...")
        self.log("Loading video file...")
        video = VideoFileClip(self.input_path)

        font_size = self.font_size
        font_name = self.font_name
        font_color = self.font_color
        stroke_color = self.stroke_color
        stroke_width = self.stroke_width
        bg_opacity = self.bg_opacity

        def generator(txt):
            text_clip = TextClip(
                txt,
                fontsize=font_size,
                font=font_name,
                color=font_color,
                stroke_color=stroke_color,
                stroke_width=stroke_width,
                method="caption",
                size=(video.w * 0.9, None),
                align="center",
            )
            padding_x = 40
            padding_y = 20
            bg = ColorClip(
                size=(int(text_clip.w + padding_x), int(text_clip.h + padding_y)),
                color=(0, 0, 0),
            ).set_opacity(bg_opacity)
            return CompositeVideoClip(
                [bg.set_position("center"), text_clip.set_position("center")],
                size=(int(text_clip.w + padding_x), int(text_clip.h + padding_y)),
            )

        self.set_progress(60, "Compositing captions onto video...")
        self.log("Compositing captions onto video...")
        subtitles = SubtitlesClip(subs, generator)

        final = CompositeVideoClip([
            video,
            subtitles.set_position(("center", self._pos_fraction()), relative=True),
        ])

        self.set_progress(65, "Starting render...")
        self.log(f"Rendering to: {self.output_path}")

        ui_logger = UiProgressLogger(self.set_progress, start_pct=65, end_pct=99)
        final.write_videofile(self.output_path, logger=ui_logger)

        video.close()
        final.close()

        self.set_progress(100, "Done!")
        self.log("Finished successfully.")

    def _pos_fraction(self):
        return {"Top": 0.08, "Center": 0.45, "Bottom": 0.80}.get(self.position, 0.80)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class CaptionApp(tk.Tk):
    PREVIEW_W = 480
    PREVIEW_H = 270

    def __init__(self):
        super().__init__()
        self.title("Caption Generator")
        self.geometry("620x780")
        self.resizable(False, False)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.max_words = tk.IntVar(value=4)
        self.font_size = tk.IntVar(value=45)
        self.model_name = tk.StringVar(value="base")

        available_fonts = sorted(set(tkfont.families()))
        preferred = [f for f in ["Arial", "Impact", "Verdana", "Georgia", "Comic Sans MS",
                                  "Times New Roman", "Courier New", "Tahoma"] if f in available_fonts]
        self.font_choices = preferred + [f for f in available_fonts if f not in preferred]
        self.font_family = tk.StringVar(value=preferred[0] if preferred else (available_fonts[0] if available_fonts else "Arial"))

        self.font_color = tk.StringVar(value="#ffffff")
        self.stroke_color = tk.StringVar(value="#000000")
        self.stroke_width = tk.IntVar(value=2)
        self.bg_opacity = tk.DoubleVar(value=0.8)
        self.position = tk.StringVar(value="Bottom")
        self.preview_text = tk.StringVar(value="Sample caption text")

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self.job_running = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.after(100, self._poll_queue)
        self._redraw_preview()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # Input file row
        frame_in = tk.Frame(self)
        frame_in.pack(fill="x", **pad)
        tk.Label(frame_in, text="Input video:", width=12, anchor="w").pack(side="left")
        tk.Entry(frame_in, textvariable=self.input_path).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(frame_in, text="Browse...", command=self._browse_input).pack(side="left")

        # Output file row
        frame_out = tk.Frame(self)
        frame_out.pack(fill="x", **pad)
        tk.Label(frame_out, text="Output video:", width=12, anchor="w").pack(side="left")
        tk.Entry(frame_out, textvariable=self.output_path).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(frame_out, text="Save as...", command=self._browse_output).pack(side="left")

        # --- Preview window ---
        preview_frame = tk.LabelFrame(self, text="Caption Preview")
        preview_frame.pack(fill="x", padx=10, pady=6)
        self.preview_canvas = tk.Canvas(preview_frame, width=self.PREVIEW_W, height=self.PREVIEW_H,
                                         bg="#3a3a3a", highlightthickness=0)
        self.preview_canvas.pack(padx=8, pady=8)
        entry_row = tk.Frame(preview_frame)
        entry_row.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(entry_row, text="Preview text:").pack(side="left")
        preview_entry = tk.Entry(entry_row, textvariable=self.preview_text)
        preview_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        preview_entry.bind("<KeyRelease>", lambda e: self._redraw_preview())

        # --- Caption / Whisper options ---
        frame_opts = tk.LabelFrame(self, text="Caption Options")
        frame_opts.pack(fill="x", **pad)

        row1 = tk.Frame(frame_opts)
        row1.pack(fill="x", padx=10, pady=4)
        tk.Label(row1, text="Words per caption:").pack(side="left")
        tk.Spinbox(row1, from_=1, to=10, textvariable=self.max_words, width=5).pack(side="left", padx=(6, 20))

        tk.Label(row1, text="Whisper model:").pack(side="left")
        ttk.Combobox(
            row1, textvariable=self.model_name, width=10, state="readonly",
            values=["tiny", "base", "small", "medium", "large"]
        ).pack(side="left", padx=(6, 0))

        # --- Font options ---
        frame_font = tk.LabelFrame(self, text="Font Options")
        frame_font.pack(fill="x", **pad)

        frow1 = tk.Frame(frame_font)
        frow1.pack(fill="x", padx=10, pady=4)
        tk.Label(frow1, text="Font:", width=10, anchor="w").pack(side="left")
        font_combo = ttk.Combobox(frow1, textvariable=self.font_family, width=22, state="readonly",
                                   values=self.font_choices)
        font_combo.pack(side="left", padx=(0, 16))
        font_combo.bind("<<ComboboxSelected>>", lambda e: self._redraw_preview())

        tk.Label(frow1, text="Size:").pack(side="left")
        size_spin = tk.Spinbox(frow1, from_=10, to=120, textvariable=self.font_size, width=5,
                                command=self._redraw_preview)
        size_spin.pack(side="left", padx=(6, 0))
        size_spin.bind("<KeyRelease>", lambda e: self._redraw_preview())

        frow2 = tk.Frame(frame_font)
        frow2.pack(fill="x", padx=10, pady=4)
        tk.Label(frow2, text="Text color:", width=10, anchor="w").pack(side="left")
        self.font_color_swatch = tk.Label(frow2, bg=self.font_color.get(), width=4, relief="ridge")
        self.font_color_swatch.pack(side="left")
        tk.Button(frow2, text="Choose...", command=self._pick_font_color).pack(side="left", padx=(4, 20))

        tk.Label(frow2, text="Stroke color:").pack(side="left")
        self.stroke_color_swatch = tk.Label(frow2, bg=self.stroke_color.get(), width=4, relief="ridge")
        self.stroke_color_swatch.pack(side="left")
        tk.Button(frow2, text="Choose...", command=self._pick_stroke_color).pack(side="left", padx=(4, 0))

        frow3 = tk.Frame(frame_font)
        frow3.pack(fill="x", padx=10, pady=4)
        tk.Label(frow3, text="Stroke width:", width=10, anchor="w").pack(side="left")
        stroke_spin = tk.Spinbox(frow3, from_=0, to=10, textvariable=self.stroke_width, width=5,
                                  command=self._redraw_preview)
        stroke_spin.pack(side="left", padx=(0, 20))
        stroke_spin.bind("<KeyRelease>", lambda e: self._redraw_preview())

        tk.Label(frow3, text="Background opacity:").pack(side="left")
        opacity_scale = tk.Scale(frow3, from_=0.0, to=1.0, resolution=0.05, orient="horizontal",
                                  variable=self.bg_opacity, length=140, command=lambda v: self._redraw_preview())
        opacity_scale.pack(side="left", padx=(6, 0))

        frow4 = tk.Frame(frame_font)
        frow4.pack(fill="x", padx=10, pady=4)
        tk.Label(frow4, text="Position:", width=10, anchor="w").pack(side="left")
        pos_combo = ttk.Combobox(frow4, textvariable=self.position, width=10, state="readonly",
                                  values=["Top", "Center", "Bottom"])
        pos_combo.pack(side="left")
        pos_combo.bind("<<ComboboxSelected>>", lambda e: self._redraw_preview())

        # Run button
        self.run_button = tk.Button(self, text="Generate Captions", command=self._start_job,
                                     bg="#2d7cf0", fg="white", font=("Segoe UI", 11, "bold"), height=2)
        self.run_button.pack(fill="x", padx=10, pady=(10, 6))

        # Progress bar
        self.progress = ttk.Progressbar(self, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 4))
        self.progress_label = tk.Label(self, text="Idle", anchor="w")
        self.progress_label.pack(fill="x", padx=10)

        # Log box
        log_frame = tk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    # --- color pickers ---
    def _pick_font_color(self):
        color = colorchooser.askcolor(color=self.font_color.get(), title="Choose text color")
        if color and color[1]:
            self.font_color.set(color[1])
            self.font_color_swatch.config(bg=color[1])
            self._redraw_preview()

    def _pick_stroke_color(self):
        color = colorchooser.askcolor(color=self.stroke_color.get(), title="Choose stroke color")
        if color and color[1]:
            self.stroke_color.set(color[1])
            self.stroke_color_swatch.config(bg=color[1])
            self._redraw_preview()

    # --- live preview (pure tkinter Canvas, mimics stroke via offset text draws) ---
    def _redraw_preview(self):
        c = self.preview_canvas
        c.delete("all")
        c.create_rectangle(0, 0, self.PREVIEW_W, self.PREVIEW_H, fill="#3a3a3a", outline="")

        text = self.preview_text.get() or "Sample caption text"
        family = self.font_family.get()
        size = max(6, int(self.font_size.get() * (self.PREVIEW_W / 1280)))  # scale down for preview canvas
        size = max(size, 10)
        stroke_w = self.stroke_width.get()
        font = (family, size, "bold")

        # measure text to size the background box
        tmp = tk.Label(self, text=text, font=font)
        tmp.update_idletasks()
        text_w = tmp.winfo_reqwidth()
        text_h = tmp.winfo_reqheight()
        tmp.destroy()

        pad_x, pad_y = 24, 14
        box_w = min(text_w + pad_x, self.PREVIEW_W - 20)
        box_h = text_h + pad_y

        y_frac = {"Top": 0.15, "Center": 0.5, "Bottom": 0.85}.get(self.position.get(), 0.85)
        cx = self.PREVIEW_W / 2
        cy = self.PREVIEW_H * y_frac

        # background box
        opacity = self.bg_opacity.get()
        stipple = "" if opacity >= 0.95 else ("gray50" if opacity >= 0.6 else ("gray25" if opacity >= 0.3 else "gray12"))
        c.create_rectangle(cx - box_w / 2, cy - box_h / 2, cx + box_w / 2, cy + box_h / 2,
                            fill="black", outline="", stipple=stipple if stipple else "")

        # fake stroke
        if stroke_w > 0:
            offsets = [(dx, dy) for dx in range(-stroke_w, stroke_w + 1) for dy in range(-stroke_w, stroke_w + 1)
                       if dx != 0 or dy != 0]
            for dx, dy in offsets:
                c.create_text(cx + dx, cy + dy, text=text, font=font, fill=self.stroke_color.get())

        c.create_text(cx, cy, text=text, font=font, fill=self.font_color.get())

    # --- file dialogs ---
    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)
            if not self.output_path.get():
                base, ext = os.path.splitext(path)
                self.output_path.set(base + "_captioned.mp4")

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output as",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if path:
            self.output_path.set(path)

    # --- job control ---
    def _start_job(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Busy", "A job is already running.")
            return

        in_path = self.input_path.get().strip()
        out_path = self.output_path.get().strip()

        if not in_path or not os.path.isfile(in_path):
            messagebox.showerror("Error", "Please select a valid input video file.")
            return
        if not out_path:
            messagebox.showerror("Error", "Please choose an output file path.")
            return

        self.run_button.config(state="disabled", text="Processing...")
        self._set_progress(0, "Starting...")
        self._clear_log()
        self.job_running = True

        job = CaptionJob(
            input_path=in_path,
            output_path=out_path,
            max_words=self.max_words.get(),
            font_name=self.font_family.get(),
            font_size=self.font_size.get(),
            font_color=self.font_color.get(),
            stroke_color=self.stroke_color.get(),
            stroke_width=self.stroke_width.get(),
            bg_opacity=self.bg_opacity.get(),
            position=self.position.get(),
            model_name=self.model_name.get(),
            log_fn=self._log_threadsafe,
            progress_fn=self._progress_threadsafe,
        )

        def target():
            try:
                job.run()
                self.msg_queue.put(("done", None))
            except BaseException as e:
                self.msg_queue.put(("error", "".join(traceback.format_exception(type(e), e, e.__traceback__))))

        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _on_close_request(self):
        if self.job_running:
            proceed = messagebox.askyesno(
                "Job in progress",
                "A captioning job is still running. Closing now will lose the "
                "output video.\n\nAre you sure you want to quit?",
            )
            if not proceed:
                return
        self.destroy()

    # --- thread-safe message passing ---
    def _log_threadsafe(self, msg):
        self.msg_queue.put(("log", msg))

    def _progress_threadsafe(self, pct, msg):
        self.msg_queue.put(("progress", (pct, msg)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    pct, msg = payload
                    self._set_progress(pct, msg)
                elif kind == "done":
                    self.job_running = False
                    self.run_button.config(state="normal", text="Generate Captions")
                    messagebox.showinfo("Done", "Captioned video saved successfully!")
                elif kind == "error":
                    self.job_running = False
                    self.run_button.config(state="normal", text="Generate Captions")
                    self._append_log("ERROR:\n" + payload)
                    self._set_progress(0, "Failed")
                    messagebox.showerror("Error", "Something went wrong. See log for details.")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # --- UI helpers ---
    def _set_progress(self, pct, msg):
        self.progress["value"] = pct
        self.progress_label.config(text=f"{msg} ({pct}%)" if pct else msg)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _append_log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


if __name__ == "__main__":
    app = CaptionApp()
    app.mainloop()
