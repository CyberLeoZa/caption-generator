# Caption Generator

A simple desktop app that automatically transcribes a video using
[OpenAI Whisper](https://github.com/openai/whisper) and burns styled,
word-chunked captions onto it using [MoviePy](https://zulko.github.io/moviepy/).

Includes a Tkinter GUI with:

- File picker for input/output video
- Adjustable Whisper model size 
- Words-per-caption control
- Font family, size, color, stroke color/width, background opacity, and
  caption position (top / center / bottom)
- A live caption preview window
- A real, frame-accurate progress bar during rendering
- A log panel for diagnostics

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/download.html) available on your system `PATH`
- [ImageMagick](https://imagemagick.org/script/download.php) installed
  (required by MoviePy's `TextClip`)

## Setup

```bash
git clone [https://github.com/yourusername/caption-generator.git](https://github.com/CyberLeoZa/caption-generator.git)
cd caption-generator
pip install -r requirements.txt
```

### ImageMagick path (Windows)

Open `caption_generator.py` and update this line near the top to match your
ImageMagick install location:

```python
IMAGEMAGICK_BINARY = r"C:\Program Files\ImageMagick-7.1.2-Q16\magick.exe"
```

On macOS/Linux this is usually auto-detected and can be left as-is (the
script only applies the override if the path exists).

## Usage

```bash
python caption_generator.py
```

1. Browse to select an input video.
2. Pick an output path (auto-suggested next to the input file).
3. Adjust caption/font options and preview them live.
4. Click **Generate Captions** and watch the progress bar.
5. Find your captioned video at the output path once it finishes.

## Notes

- Larger Whisper models (`medium`, `large`) are more accurate but
  significantly slower and need more RAM/VRAM.
- The live preview approximates the final look using Tkinter's font
  rendering; the actual render uses ImageMagick, so minor differences in
  rendering are expected.
- Don't close the app while a job is running — you'll be warned if you try,
  since it will abort the video render in progress.

