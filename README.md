# CleanStream Station

A robust, Textual-based terminal user interface (TUI) for downloading and sanitizing video content.

This tool aims to provide a safe and streamlined workflow for archiving web media. It automatically downloads videos using `yt-dlp` and immediately "sanitizes" them using `ffmpeg`—stripping metadata, re-encoding to a standard format, and ensuring standardized filenames while preserving non-ASCII (e.g., Japanese) characters.

![TUI Screenshot](https://via.placeholder.com/800x400?text=TUI+Screenshot+Placeholder)

## Features

- **Interactive TUI**: Built with [Textual](https://github.com/Textualize/textual) for a rich terminal experience.
- **Safe Archiving**: 
  - Downloads via `yt-dlp`.
  - Automatically re-encodes (sanitizes) using `ffmpeg` (CRF 23, AAC).
  - Removes metadata and chapters.
- **Concurrent Processing**: Handles multiple tasks in parallel (Default limit: 3) to optimize resource usage.
- **Real-time Stats**: 
  - Visual progress bars for download and conversion.
  - Live speed, ETA, and file size reduction stats.
- **Smart Filenaming**: 
  - Preserves Japanese/Unicode characters.
  - Automatically removes filesystem-unsafe characters (`<`, `>`, `:`, `"`, `/`, `\`, `|`, `?`, `*`).
  - Handles filename collisions automatically (e.g., `_1.mp4`).

## Prerequisites

- **Docker** & **Docker Compose**
- (Optional) Python 3.11+ if running locally without Docker.

## Installation & Usage

### Using Docker (Recommended)

1. Clone the repository.
2. Build and run the container:

```bash
docker compose run --rm downloader
```

*(Note: Ensure your `docker-compose.yml` maps the volumes for usage, e.g., `./downloads` and `./safe_output`)*

### Manual Operation

1. Install dependencies:
   ```bash
   pip install textual yt-dlp
   # ffmpeg must be installed on your system
   ```

2. Run the application:
   ```bash
   python station.py
   ```

## Workflow

1. **Input**: Paste a URL into the input box at the top.
2. **Download**: The system fetches the video using `yt-dlp`.
3. **Sanitize**: The video is immediately re-encoded to remove potential tracking metadata and standardize the codec.
4. **Result**: The clean file is saved to the output directory.

## Configuration

You can adjust the following constants in the script:

- `MAX_CONCURRENT_TASKS`: Number of parallel processing tasks (Default: 3).
- `DOWNLOAD_DIR` / `SAFE_DIR`: Input/Output directories.

## License

MIT License
