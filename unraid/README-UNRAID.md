# ReelIndex on Unraid

ReelIndex uses a dedicated all-in-one image on Unraid. The image contains the React frontend, nginx reverse proxy, FastAPI backend, SQLite database support, and ffprobe. This avoids requiring Docker Compose or two separately managed containers.

## Install

1. Extract the ReelIndex project to an Unraid-accessible folder, for example:

   `/mnt/user/appdata/reelindex-build`

2. Open **Unraid → Terminal** and run:

   ```bash
   cd /mnt/user/appdata/reelindex-build/reelindex
   ./unraid/install-reelindex.sh
   ```

3. Open **Docker → Add Container**.
4. Select **ReelIndex** from the **Template** list.
5. Review these mappings:

   - Application Data: `/mnt/user/appdata/reelindex` → `/data` (read/write)
   - Movie Library: your movie share → `/media` (**read-only**)
   - WebUI: host port `8080` → container port `8080`

6. Select **Apply**, then open **WebUI**.
7. In ReelIndex, add a **Filesystem** source with the container path `/media` and start a scan.

## Additional movie shares

Edit the ReelIndex container in Unraid, select **Add another Path, Port, Variable, Label or Device**, and add another path such as:

- Host path: `/mnt/user/Movies-4K`
- Container path: `/media4k`
- Access mode: **Read Only**

Create a second filesystem source in ReelIndex using `/media4k`.

## Plex, Jellyfin, and Emby path mapping

When the media server reports a path different from the container path, configure ReelIndex's source path mapping. Example:

- Server prefix: `/movies`
- Mounted container prefix: `/media`

The media path must also exist as a read-only Unraid volume mapping for ReelIndex to run ffprobe directly. Without a local mapping, ReelIndex falls back to technical metadata returned by the media server.

## Update after source-code changes

Run the installer again to rebuild the image:

```bash
cd /mnt/user/appdata/reelindex-build/reelindex
./unraid/install-reelindex.sh
```

Then edit the ReelIndex container and select **Apply** to recreate it from the rebuilt local image. Application data remains in `/mnt/user/appdata/reelindex`.

## Reset

Remove the container through Unraid. To also remove the inventory, credentials, and poster cache, delete:

`/mnt/user/appdata/reelindex`

The movie mapping remains read-only and is never modified by ReelIndex.

## Registry-ready template

The included `my-ReelIndex.xml` uses the local image name `reelindex:unraid`. Once the image is published to Docker Hub or GHCR, replace the `<Repository>` value with the published image name and optionally populate `<Registry>`, `<Project>`, `<Support>`, `<TemplateURL>`, and `<Icon>` for Community Applications distribution.

## ReelIndex icon

The installer copies `reelindex-icon.png` to the persistent Unraid Docker icon directory and references it from the template. The same artwork is built into the web interface as the favicon, Apple touch icon, and web app icon. If an older blank icon remains cached, refresh the Docker page after recreating the container.
