package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const appVersion = "1.4.8"
const packageVersion = "1.4.8.2"

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

func fail(err error) {
	msg("ReelIndex Setup", "Installation failed:\n\n"+err.Error()+"\n\nNo downloaded scripts or network installers were run.", 0x10)
}

func localData() string {
	d, _ := os.UserCacheDir()
	return filepath.Join(d, "ReelIndex")
}

func stopExistingServer() {
	pidPath := filepath.Join(localData(), "server.pid")
	if raw, err := os.ReadFile(pidPath); err == nil {
		pid := strings.TrimSpace(string(raw))
		if pid != "" {
			_ = exec.Command("taskkill.exe", "/PID", pid, "/T", "/F").Run()
		}
	}
	_ = os.Remove(pidPath)
	_ = os.Remove(filepath.Join(localData(), "server.port"))
}

func cleanRelative(name string) (string, error) {
	clean := filepath.Clean(filepath.FromSlash(name))
	if clean == "." || filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("invalid payload path: %s", name)
	}
	return clean, nil
}

func unzip(data []byte, destination string) error {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return fmt.Errorf("open embedded payload: %w", err)
	}
	for _, item := range r.File {
		relative, err := cleanRelative(item.Name)
		if err != nil {
			return err
		}
		path := filepath.Join(destination, relative)
		if item.FileInfo().IsDir() {
			if err := os.MkdirAll(path, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return err
		}
		source, err := item.Open()
		if err != nil {
			return err
		}
		target, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
		if err != nil {
			source.Close()
			return err
		}
		_, copyErr := io.Copy(target, source)
		closeErr := target.Close()
		source.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}

func parseManifest(path string) (map[string]string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read payload manifest: %w", err)
	}
	entries := make(map[string]string)
	for lineNumber, line := range strings.Split(strings.ReplaceAll(string(raw), "\r\n", "\n"), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "  ", 2)
		if len(parts) != 2 || len(parts[0]) != 64 {
			return nil, fmt.Errorf("invalid manifest entry on line %d", lineNumber+1)
		}
		if _, err := hex.DecodeString(parts[0]); err != nil {
			return nil, fmt.Errorf("invalid manifest digest on line %d", lineNumber+1)
		}
		relative, err := cleanRelative(parts[1])
		if err != nil {
			return nil, err
		}
		entries[filepath.Clean(relative)] = strings.ToLower(parts[0])
	}
	if len(entries) == 0 {
		return nil, fmt.Errorf("payload manifest is empty")
	}
	return entries, nil
}

func verifyPayload(root string) error {
	manifestPath := filepath.Join(root, "manifest.sha256")
	expected, err := parseManifest(manifestPath)
	if err != nil {
		return err
	}
	seen := make(map[string]bool)
	err = filepath.Walk(root, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.IsDir() {
			return nil
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		relative = filepath.Clean(relative)
		if relative == "manifest.sha256" {
			return nil
		}
		digest, ok := expected[relative]
		if !ok {
			return fmt.Errorf("unlisted payload file: %s", relative)
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		hash := sha256.New()
		_, copyErr := io.Copy(hash, file)
		closeErr := file.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
		actual := hex.EncodeToString(hash.Sum(nil))
		if !strings.EqualFold(actual, digest) {
			return fmt.Errorf("payload checksum mismatch: %s", relative)
		}
		seen[relative] = true
		return nil
	})
	if err != nil {
		return err
	}
	missing := make([]string, 0)
	for relative := range expected {
		if !seen[relative] {
			missing = append(missing, relative)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return fmt.Errorf("payload files missing: %s", strings.Join(missing, ", "))
	}
	return nil
}

func writeCommand(path, executable string, arguments ...string) error {
	quotedArgs := make([]string, 0, len(arguments))
	for _, argument := range arguments {
		quotedArgs = append(quotedArgs, "\""+strings.ReplaceAll(argument, "\"", "\"\"")+"\"")
	}
	command := "@echo off\r\nstart \"\" \"" + executable + "\""
	if len(quotedArgs) > 0 {
		command += " " + strings.Join(quotedArgs, " ")
	}
	command += "\r\n"
	return os.WriteFile(path, []byte(command), 0644)
}

func configureShortcuts(installDir string) error {
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "ReelIndex")
	if err := os.RemoveAll(startMenu); err != nil {
		return err
	}
	if err := os.MkdirAll(startMenu, 0755); err != nil {
		return err
	}
	launcher := filepath.Join(installDir, "ReelIndex.exe")
	commands := []struct {
		name string
		args []string
	}{
		{"ReelIndex.cmd", nil},
		{"Stop ReelIndex.cmd", []string{"--stop"}},
		{"View ReelIndex Logs.cmd", []string{"--logs"}},
		{"Uninstall ReelIndex.cmd", nil},
	}
	for _, command := range commands {
		target := launcher
		if command.name == "Uninstall ReelIndex.cmd" {
			target = filepath.Join(installDir, "Uninstall ReelIndex.exe")
		}
		if err := writeCommand(filepath.Join(startMenu, command.name), target, command.args...); err != nil {
			return err
		}
	}
	return nil
}

func regAdd(key, name, valueType, value string) error {
	args := []string{"add", key, "/f"}
	if name == "" {
		args = append(args, "/ve")
	} else {
		args = append(args, "/v", name)
	}
	args = append(args, "/t", valueType, "/d", value)
	command := exec.Command("reg.exe", args...)
	if output, err := command.CombinedOutput(); err != nil {
		return fmt.Errorf("registry update failed: %w (%s)", err, strings.TrimSpace(string(output)))
	}
	return nil
}

func configureUninstall(installDir string) error {
	key := `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReelIndex`
	values := []struct {
		name      string
		valueType string
		value     string
	}{
		{"DisplayName", "REG_SZ", "ReelIndex Movie Inventory"},
		{"DisplayVersion", "REG_SZ", packageVersion},
		{"Publisher", "REG_SZ", "ReelIndex"},
		{"InstallLocation", "REG_SZ", installDir},
		{"DisplayIcon", "REG_SZ", filepath.Join(installDir, "ReelIndex.exe")},
		{"UninstallString", "REG_SZ", `"` + filepath.Join(installDir, "Uninstall ReelIndex.exe") + `"`},
		{"NoModify", "REG_DWORD", "1"},
		{"NoRepair", "REG_DWORD", "1"},
	}
	for _, item := range values {
		if err := regAdd(key, item.name, item.valueType, item.value); err != nil {
			return err
		}
	}
	return nil
}

func install() error {
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return fmt.Errorf("LOCALAPPDATA is unavailable")
	}
	parent := filepath.Join(localAppData, "Programs")
	installDir := filepath.Join(parent, "ReelIndex")
	staging := filepath.Join(parent, fmt.Sprintf(".ReelIndex-staging-%d", time.Now().UnixNano()))
	backup := filepath.Join(parent, fmt.Sprintf(".ReelIndex-backup-%d", time.Now().UnixNano()))
	if err := os.MkdirAll(parent, 0755); err != nil {
		return err
	}
	defer os.RemoveAll(staging)
	defer os.RemoveAll(backup)

	if err := unzip(payload, staging); err != nil {
		return err
	}
	if err := verifyPayload(staging); err != nil {
		return fmt.Errorf("embedded payload verification failed: %w", err)
	}
	if _, err := os.Stat(filepath.Join(staging, "runtime", "pythonw.exe")); err != nil {
		return fmt.Errorf("bundled Python runtime is missing")
	}
	if _, err := os.Stat(filepath.Join(staging, "ReelIndex.exe")); err != nil {
		return fmt.Errorf("ReelIndex launcher is missing")
	}

	stopExistingServer()
	if _, err := os.Stat(installDir); err == nil {
		if err := os.Rename(installDir, backup); err != nil {
			return fmt.Errorf("back up existing installation: %w", err)
		}
	}
	if err := os.Rename(staging, installDir); err != nil {
		if _, backupErr := os.Stat(backup); backupErr == nil {
			_ = os.Rename(backup, installDir)
		}
		return fmt.Errorf("activate verified installation: %w", err)
	}
	rollback := true
	defer func() {
		if rollback {
			_ = os.RemoveAll(installDir)
			if _, err := os.Stat(backup); err == nil {
				_ = os.Rename(backup, installDir)
			}
		}
	}()

	if err := configureShortcuts(installDir); err != nil {
		return err
	}
	if err := configureUninstall(installDir); err != nil {
		return err
	}
	rollback = false
	_ = os.RemoveAll(backup)
	if err := exec.Command(filepath.Join(installDir, "ReelIndex.exe")).Start(); err != nil {
		return fmt.Errorf("launch ReelIndex: %w", err)
	}
	return nil
}

func main() {
	if msg(
		"ReelIndex Setup",
		"Install ReelIndex Movie Inventory "+appVersion+" (secure Windows package "+packageVersion+") for this Windows user?\n\nThis offline installer does not run shell scripts, download files, or access the network. Its embedded payload is verified with SHA-256 before installation.",
		0x44|0x20,
	) != 6 {
		return
	}
	if err := install(); err != nil {
		fail(err)
		return
	}
	msg("ReelIndex Setup", "ReelIndex "+appVersion+" was installed successfully from secure package "+packageVersion+" and is opening in your default browser.", 0x40)
}
