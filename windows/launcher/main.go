package main

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var (
	user32      = syscall.NewLazyDLL("user32.dll")
	messageBoxW = user32.NewProc("MessageBoxW")
)

func messageBox(title, text string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := messageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
	return int(r)
}
func localData() string  { d, _ := os.UserCacheDir(); return filepath.Join(d, "ReelIndex") }
func installDir() string { e, _ := os.Executable(); return filepath.Dir(e) }
func readPort() int {
	b, e := os.ReadFile(filepath.Join(localData(), "server.port"))
	if e != nil {
		return 0
	}
	p, _ := strconv.Atoi(strings.TrimSpace(string(b)))
	return p
}
func healthy(port int) bool {
	if port < 1 {
		return false
	}
	c := http.Client{Timeout: 700 * time.Millisecond}
	r, e := c.Get(fmt.Sprintf("http://127.0.0.1:%d/api/health", port))
	if e != nil {
		return false
	}
	defer r.Body.Close()
	return r.StatusCode == 200
}
func openURL(url string) { exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url).Start() }
func stopServer() {
	b, e := os.ReadFile(filepath.Join(localData(), "server.pid"))
	if e == nil {
		pid := strings.TrimSpace(string(b))
		exec.Command("taskkill.exe", "/PID", pid, "/T", "/F").Run()
	}
	os.Remove(filepath.Join(localData(), "server.pid"))
	os.Remove(filepath.Join(localData(), "server.port"))
}
func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--stop" {
		stopServer()
		messageBox("ReelIndex", "ReelIndex has been stopped.", 0x40)
		return
	}
	if len(args) > 0 && args[0] == "--logs" {
		os.MkdirAll(filepath.Join(localData(), "logs"), 0755)
		exec.Command("explorer.exe", filepath.Join(localData(), "logs")).Start()
		return
	}
	if p := readPort(); healthy(p) {
		openURL(fmt.Sprintf("http://127.0.0.1:%d/", p))
		return
	}
	py := filepath.Join(installDir(), "runtime", "pythonw.exe")
	script := filepath.Join(installDir(), "app", "windows_launcher.py")
	if _, e := os.Stat(py); e != nil {
		messageBox("ReelIndex", "The bundled Python runtime is missing. Reinstall ReelIndex.", 0x10)
		return
	}
	cmd := exec.Command(py, script)
	cmd.Dir = installDir()
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	if e := cmd.Start(); e != nil {
		messageBox("ReelIndex", "Could not start ReelIndex: "+e.Error(), 0x10)
		return
	}
	for i := 0; i < 80; i++ {
		time.Sleep(250 * time.Millisecond)
		if p := readPort(); healthy(p) {
			openURL(fmt.Sprintf("http://127.0.0.1:%d/", p))
			return
		}
	}
	messageBox("ReelIndex", "ReelIndex started but the web interface did not become ready. Open the Start Menu shortcut 'View ReelIndex Logs' for details.", 0x30)
}
