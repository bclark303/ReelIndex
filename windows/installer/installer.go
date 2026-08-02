package main

import (
	"archive/zip"
	"bytes"
	_ "embed"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

//go:embed payload.zip
var payload []byte
var user32 = syscall.NewLazyDLL("user32.dll")
var messageBoxW = user32.NewProc("MessageBoxW")

func msg(title, text string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := messageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
	return int(r)
}
func fail(e error) {
	msg("ReelIndex Setup", "Installation failed:\n\n"+e.Error()+"\n\nA setup log may be available in your temporary folder.", 0x10)
}
func unzip(data []byte, dest string) error {
	r, e := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if e != nil {
		return e
	}
	for _, f := range r.File {
		clean := filepath.Clean(f.Name)
		if strings.Contains(clean, "..") || filepath.IsAbs(clean) {
			return fmt.Errorf("invalid payload path: %s", f.Name)
		}
		path := filepath.Join(dest, clean)
		if f.FileInfo().IsDir() {
			if e = os.MkdirAll(path, 0755); e != nil {
				return e
			}
			continue
		}
		if e = os.MkdirAll(filepath.Dir(path), 0755); e != nil {
			return e
		}
		src, e := f.Open()
		if e != nil {
			return e
		}
		out, e := os.Create(path)
		if e != nil {
			src.Close()
			return e
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
func main() {
	if msg("ReelIndex Setup", "Install ReelIndex Movie Inventory for this Windows user?\n\nSetup installs ReelIndex 1.4.5 and its Windows runtime. Internet access is required by this standard installer; an existing offline-builder package can capture a fully self-contained installer.", 0x44|0x20) != 6 {
		return
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		fail(fmt.Errorf("LOCALAPPDATA is unavailable"))
		return
	}
	dir := filepath.Join(local, "Programs", "ReelIndex")
	if b, e := os.ReadFile(filepath.Join(local, "ReelIndex", "server.pid")); e == nil {
		exec.Command("taskkill.exe", "/PID", strings.TrimSpace(string(b)), "/T", "/F").Run()
	}
	os.RemoveAll(dir)
	if e := os.MkdirAll(dir, 0755); e != nil {
		fail(e)
		return
	}
	if e := unzip(payload, dir); e != nil {
		fail(e)
		return
	}
	log := filepath.Join(os.TempDir(), "ReelIndex-install.log")
	ps := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(dir, "install-runtime.ps1"), "-InstallDir", dir)
	ps.Dir = dir
	ps.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000010}
	if e := ps.Run(); e != nil {
		fail(fmt.Errorf("runtime setup failed (%v). See %s", e, log))
		return
	}
	msg("ReelIndex Setup", "ReelIndex was installed successfully. It will now open in your default browser.", 0x40)
	exec.Command(filepath.Join(dir, "ReelIndex.exe")).Start()
}
