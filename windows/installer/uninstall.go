package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var user32 = syscall.NewLazyDLL("user32.dll")
var messageBoxW = user32.NewProc("MessageBoxW")

func msg(title, text string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := messageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
	return int(r)
}
func localData() string { d, _ := os.UserCacheDir(); return filepath.Join(d, "ReelIndex") }
func stop() {
	b, e := os.ReadFile(filepath.Join(localData(), "server.pid"))
	if e == nil {
		exec.Command("taskkill.exe", "/PID", strings.TrimSpace(string(b)), "/T", "/F").Run()
	}
}
func main() {
	result := msg("Uninstall ReelIndex", "Remove ReelIndex?\n\nYes: remove the application and cached database/posters.\nNo: remove the application but keep cached data.\nCancel: do nothing.", 0x23|0x30)
	if result == 2 {
		return
	}
	removeData := result == 6
	stop()
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	appdata := os.Getenv("APPDATA")
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop", "ReelIndex.lnk")
	os.RemoveAll(filepath.Join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "ReelIndex"))
	os.Remove(desktop)
	exec.Command("reg.exe", "delete", `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReelIndex`, "/f").Run()
	dataCmd := ""
	if removeData {
		dataCmd = fmt.Sprintf(` & rmdir /S /Q "%s"`, localData())
	}
	command := fmt.Sprintf(`ping 127.0.0.1 -n 3 >nul & rmdir /S /Q "%s"%s`, dir, dataCmd)
	cmd := exec.Command("cmd.exe", "/C", command)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	cmd.Start()
	msg("ReelIndex", "ReelIndex has been removed.", 0x40)
}
