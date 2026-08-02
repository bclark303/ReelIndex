package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const footerSize = 72

var payloadMagic = [32]byte{'R', 'E', 'E', 'L', 'I', 'N', 'D', 'E', 'X', '-', 'O', 'F', 'F', 'L', 'I', 'N', 'E', '-', 'P', 'A', 'Y', 'L', 'O', 'A', 'D', '-', 'V', '1'}

var user32 = syscall.NewLazyDLL("user32.dll")
var messageBoxW = user32.NewProc("MessageBoxW")

func msg(title, text string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := messageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
	return int(r)
}

func fail(err error) {
	msg("ReelIndex Offline Setup", "Installation failed:\n\n"+err.Error()+"\n\nThe existing ReelIndex data directory was not removed.", 0x10)
}

func stopExisting() {
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return
	}
	pidPath := filepath.Join(local, "ReelIndex", "server.pid")
	b, err := os.ReadFile(pidPath)
	if err == nil {
		pid := strings.TrimSpace(string(b))
		if pid != "" {
			cmd := exec.Command("taskkill.exe", "/PID", pid, "/T", "/F")
			cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
			_ = cmd.Run()
			time.Sleep(600 * time.Millisecond)
		}
	}
	_ = os.Remove(pidPath)
	_ = os.Remove(filepath.Join(local, "ReelIndex", "server.port"))
}

func readPayload() (*zip.Reader, error) {
	exePath, err := os.Executable()
	if err != nil {
		return nil, err
	}
	f, err := os.Open(exePath)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if st.Size() <= footerSize {
		return nil, errors.New("offline payload is missing")
	}

	footer := make([]byte, footerSize)
	if _, err = f.ReadAt(footer, st.Size()-footerSize); err != nil {
		return nil, err
	}
	if !bytes.Equal(footer[:32], payloadMagic[:]) {
		return nil, errors.New("offline payload footer is invalid")
	}
	payloadSize := int64(binary.LittleEndian.Uint64(footer[32:40]))
	if payloadSize <= 0 || payloadSize > st.Size()-footerSize {
		return nil, errors.New("offline payload size is invalid")
	}
	payloadStart := st.Size() - footerSize - payloadSize

	section := io.NewSectionReader(f, payloadStart, payloadSize)
	h := sha256.New()
	if _, err = io.Copy(h, section); err != nil {
		return nil, err
	}
	if !bytes.Equal(h.Sum(nil), footer[40:72]) {
		return nil, errors.New("offline payload integrity check failed")
	}

	return zip.NewReader(io.NewSectionReader(f, payloadStart, payloadSize), payloadSize)
}

func safeExtract(zr *zip.Reader, dest string) error {
	root := filepath.Clean(dest) + string(os.PathSeparator)
	for _, zf := range zr.File {
		clean := filepath.Clean(filepath.FromSlash(zf.Name))
		if clean == "." || filepath.IsAbs(clean) || filepath.VolumeName(clean) != "" || strings.HasPrefix(clean, "..") {
			return fmt.Errorf("invalid payload path: %s", zf.Name)
		}
		target := filepath.Join(dest, clean)
		if target != filepath.Clean(dest) && !strings.HasPrefix(filepath.Clean(target)+string(os.PathSeparator), root) {
			return fmt.Errorf("payload path escapes install directory: %s", zf.Name)
		}
		if zf.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return err
		}
		src, err := zf.Open()
		if err != nil {
			return err
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
		if err != nil {
			src.Close()
			return err
		}
		_, copyErr := io.Copy(out, src)
		closeErr := out.Close()
		src.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}

type manifest struct {
	Version string `json:"version"`
}

func readVersion(dir string) string {
	b, err := os.ReadFile(filepath.Join(dir, "offline-manifest.json"))
	if err != nil {
		return "offline"
	}
	var m manifest
	if json.Unmarshal(b, &m) == nil && strings.TrimSpace(m.Version) != "" {
		return strings.TrimSpace(m.Version)
	}
	return "offline"
}

func runConfigure(dir, version string) error {
	script := filepath.Join(dir, "configure-offline.ps1")
	logPath := filepath.Join(os.TempDir(), "ReelIndex-offline-install.log")
	cmd := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-InstallDir", dir, "-Version", version)
	cmd.Dir = dir
	log, err := os.Create(logPath)
	if err == nil {
		defer log.Close()
		cmd.Stdout = log
		cmd.Stderr = log
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000010}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("offline runtime validation/configuration failed (%v). See %s", err, logPath)
	}
	_ = os.Remove(script)
	return nil
}

func main() {
	if msg("ReelIndex Offline Setup", "Install ReelIndex Movie Inventory for this Windows user?\n\nThis package is fully self-contained. It installs the bundled Python runtime, Python packages, MediaInfo, and ffprobe without downloading anything.\n\nYour existing ReelIndex database, sources, credentials, posters, and logs are preserved.", 0x44|0x20) != 6 {
		return
	}

	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		fail(errors.New("LOCALAPPDATA is unavailable"))
		return
	}
	installDir := filepath.Join(local, "Programs", "ReelIndex")
	backupDir := installDir + ".offline-backup"

	zr, err := readPayload()
	if err != nil {
		fail(err)
		return
	}

	stopExisting()
	_ = os.RemoveAll(backupDir)
	if _, err = os.Stat(installDir); err == nil {
		if err = os.Rename(installDir, backupDir); err != nil {
			fail(fmt.Errorf("could not back up the existing installation: %w", err))
			return
		}
	}

	rollback := func() {
		_ = os.RemoveAll(installDir)
		if _, e := os.Stat(backupDir); e == nil {
			_ = os.Rename(backupDir, installDir)
		}
	}

	if err = os.MkdirAll(installDir, 0755); err != nil {
		rollback()
		fail(err)
		return
	}
	if err = safeExtract(zr, installDir); err != nil {
		rollback()
		fail(err)
		return
	}
	version := readVersion(installDir)
	if err = runConfigure(installDir, version); err != nil {
		rollback()
		fail(err)
		return
	}

	_ = os.RemoveAll(backupDir)
	msg("ReelIndex Offline Setup", "ReelIndex "+version+" was installed successfully with no network downloads. It will now open in your default browser.", 0x40)
	_ = exec.Command(filepath.Join(installDir, "ReelIndex.exe")).Start()
}
