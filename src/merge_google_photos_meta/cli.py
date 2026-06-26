from datetime import datetime
from importlib.resources import files
from pathlib import Path
import shutil

import typer

from merge_google_photos_meta.exiftool.metadata import (
    read_metadata_batch,
    write_metadata_batch,
)

from .exiftool import ExifToolNotFound, read_metadata, resolve_exiftool, write_metadata

app = typer.Typer()


@app.command()
def main(
    google_photos_dir: str = typer.Argument(
        ..., help="Path to the Google Photos directory"
    ),
):
    exiftool_path = preflight()

    media_paths = [
        Path(google_photos_dir) / "6EC2638B-0264-47EC-80CB-6F074C4CC156.mp4",
        Path(google_photos_dir) / "298b26d9-b901-4f25-a1aa-711d7e088876.jpg",
        Path(google_photos_dir) / "2015-06-26 05.20.33.png",
        Path(google_photos_dir) / "IMG_0003.HEIC",
        Path(google_photos_dir) / "Screenshot_3.png",
    ]

    media_output_paths = []
    # Copy the media files to the output directory for testing
    for media_path in media_paths:
        media_output_path = Path(google_photos_dir) / ".." / "output" / media_path.name
        shutil.copy(media_path, media_output_path)
        media_output_paths.append(media_output_path)

    # # Check if image file exists
    # if not image_path.exists():
    #     typer.echo(f"Image file not found: {image_path}")
    #     raise typer.Exit(code=1)

    metadatas = read_metadata_batch(
        exiftool_path, [str(path) for path in media_output_paths]
    )

    for media_path, metadata in metadatas.items():
        typer.echo(f"Metadata for {media_path}: {metadata}")

    write_metadata_batch(
        exiftool_path,
        [
            (
                str(media_output_path),
                {
                    "description": "Beach day",
                    "date_taken": datetime.strptime(
                        "2000:01:02 03:04:05", "%Y:%m:%d %H:%M:%S"
                    ),
                },
            )
        ],
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
