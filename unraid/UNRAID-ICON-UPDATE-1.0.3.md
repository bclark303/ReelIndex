# ReelIndex Unraid icon update 1.0.3

This update adds the ReelIndex artwork to:

- The Unraid Docker page
- The browser tab favicon
- Apple touch icons
- The web app manifest

## Apply to an existing source directory

Extract `reelindex-unraid-icon-update-v1.0.3.zip` over the root of the existing ReelIndex source directory, preserving paths. Then rebuild and reinstall the template:

```bash
cd /mnt/user/Ben/reelindex/unraid
./install-reelindex.sh
```

In the Unraid Docker tab, edit ReelIndex and select **Apply** so the updated icon field and rebuilt image are used.

If the previous blank Docker icon remains cached, reload the Docker page. If necessary, stop and restart the Docker service from Unraid Settings; do not manually delete Docker image data.
