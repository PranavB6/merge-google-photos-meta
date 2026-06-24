from datetime import datetime
from importlib.resources import files
from pathlib import Path
import shutil

import typer

from .exiftool import ExifToolNotFound, read_metadata, resolve_exiftool, write_metadata

app = typer.Typer()


@app.command()
def main(
    google_photos_dir: str = typer.Argument(
        ..., help="Path to the Google Photos directory"
    ),
):
    exiftool_path = preflight()

    media_path = Path(google_photos_dir) / "6EC2638B-0264-47EC-80CB-6F074C4CC156.mp4"
    media_output_path = Path(google_photos_dir) / ".." / "output" / media_path.name

    # Copy the media file to the output directory for testing
    shutil.copy(media_path, media_output_path)

    # # Check if image file exists
    # if not image_path.exists():
    #     typer.echo(f"Image file not found: {image_path}")
    #     raise typer.Exit(code=1)

    metadata = read_metadata(exiftool_path, str(media_output_path))
    typer.echo(f"Metadata for {media_output_path}: {metadata}")

    write_metadata(
        exiftool_path,
        str(media_output_path),
        {
            "description": "Beach day",
            "date_taken": datetime.strptime("2000:01:02 03:04:05", "%Y:%m:%d %H:%M:%S"),
        },
    )


def preflight():
    """Verify required external tools before running any command."""
    try:
        return resolve_exiftool()
    except ExifToolNotFound as err:
        typer.secho(str(err), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
