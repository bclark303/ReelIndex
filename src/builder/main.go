package main

import (
	"archive/zip"
	"compress/flate"
	"crypto/sha256"
	"embed"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed offline-installer-stub.exe configure-offline.ps1
var embedded embed.FS

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

func defaultInstallDir() string {
	local := os.Getenv("LOCALAPPDATA")
	return filepath.Join(local, "Programs", "ReelIndex")
}

func defaultOutput(version string) string {
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop")
	name := "ReelIndex-Windows-Offline-Setup"
	if version != "" && version != "unknown" {
		name += "-v" + version
	}
	return filepath.Join(desktop, name+".exe")
}

func versionFromInstall(dir string) string {
	candidates := []string{filepath.Join(dir, "app", "web", "index.html"), filepath.Join(dir, "app", "app", "api", "system.py")}
	re := regexp.MustCompile(`ReelIndex\s+([0-9]+(?:\.[0-9]+){1,3})`)
	re2 := regexp.MustCompile(`version[\"']?\s*[:=]\s*[\"']([0-9]+(?:\.[0-9]+){1,3})[\"']`)
	for _, p := range candidates {
		b, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		if m := re.FindSubmatch(b); len(m) == 2 {
			return string(m[1])
		}
		if m := re2.FindSubmatch(b); len(m) == 2 {
			return string(m[1])
		}
	}
	return "unknown"
}

func requiredFiles(dir string) []string {
	return []string{
		filepath.Join(dir, "ReelIndex.exe"),
		filepath.Join(dir, "Uninstall ReelIndex.exe"),
		filepath.Join(dir, "app", "windows_launcher.py"),
		filepath.Join(dir, "runtime", "python.exe"),
		filepath.Join(dir, "runtime", "pythonw.exe"),
		filepath.Join(dir, "tools", "ffprobe.exe"),
	}
}

func shouldSkip(rel string, d fs.DirEntry) bool {
	rel = filepath.ToSlash(rel)
	base := strings.ToLower(d.Name())
	if d.IsDir() && (base == "__pycache__" || base == ".pytest_cache") {
		return true
	}
	if strings.HasSuffix(base, ".pyc") || strings.HasSuffix(base, ".pyo") || strings.HasSuffix(base, ".log") {
		return true
	}
	if rel == "install-runtime.ps1" || rel == "configure-offline.ps1" || rel == "offline-manifest.json" {
		return true
	}
	if strings.HasPrefix(rel, "offline-builder/") {
		return true
	}
	return false
}

type manifest struct {
	Format            string   `json:"format"`
	Version           string   `json:"version"`
	BuiltAtUTC        string   `json:"built_at_utc"`
	FileCount         int      `json:"file_count"`
	UncompressedBytes int64    `json:"uncompressed_bytes"`
	BundledComponents []string `json:"bundled_components"`
}

type sourceFile struct {
	abs, rel string
	size     int64
}

func collectFiles(dir string) ([]sourceFile, int64, error) {
	var files []sourceFile
	var total int64
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		if shouldSkip(rel, d) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		files = append(files, sourceFile{path, filepath.ToSlash(rel), info.Size()})
		total += info.Size()
		return nil
	})
	sort.Slice(files, func(i, j int) bool { return files[i].rel < files[j].rel })
	return files, total, err
}

func addBytes(zw *zip.Writer, name string, data []byte) error {
	h := &zip.FileHeader{Name: filepath.ToSlash(name), Method: zip.Deflate}
	h.SetModTime(time.Now().UTC())
	w, err := zw.CreateHeader(h)
	if err != nil {
		return err
	}
	_, err = w.Write(data)
	return err
}

func buildZip(source, zipPath, version string) (manifest, error) {
	files, total, err := collectFiles(source)
	if err != nil {
		return manifest{}, err
	}
	out, err := os.Create(zipPath)
	if err != nil {
		return manifest{}, err
	}
	zw := zip.NewWriter(out)
	zw.RegisterCompressor(zip.Deflate, func(w io.Writer) (io.WriteCloser, error) { return flate.NewWriter(w, flate.BestSpeed) })

	for i, f := range files {
		fmt.Printf("[%d/%d] %s\n", i+1, len(files), f.rel)
		info, err := os.Stat(f.abs)
		if err != nil {
			zw.Close()
			out.Close()
			return manifest{}, err
		}
		h, err := zip.FileInfoHeader(info)
		if err != nil {
			zw.Close()
			out.Close()
			return manifest{}, err
		}
		h.Name = f.rel
		h.Method = zip.Deflate
		w, err := zw.CreateHeader(h)
		if err != nil {
			zw.Close()
			out.Close()
			return manifest{}, err
		}
		src, err := os.Open(f.abs)
		if err != nil {
			zw.Close()
			out.Close()
			return manifest{}, err
		}
		_, copyErr := io.Copy(w, src)
		src.Close()
		if copyErr != nil {
			zw.Close()
			out.Close()
			return manifest{}, copyErr
		}
	}

	script, err := embedded.ReadFile("configure-offline.ps1")
	if err != nil {
		zw.Close()
		out.Close()
		return manifest{}, err
	}
	if err = addBytes(zw, "configure-offline.ps1", script); err != nil {
		zw.Close()
		out.Close()
		return manifest{}, err
	}

	components := []string{"Python runtime and standard library", "Pinned Python site-packages", "FFmpeg ffprobe", "MediaInfo CLI when installed", "ReelIndex application and launchers"}
	m := manifest{Format: "reelindex-offline-v1", Version: version, BuiltAtUTC: time.Now().UTC().Format(time.RFC3339), FileCount: len(files) + 2, UncompressedBytes: total + int64(len(script)), BundledComponents: components}
	mb, _ := json.MarshalIndent(m, "", "  ")
	if err = addBytes(zw, "offline-manifest.json", append(mb, '\n')); err != nil {
		zw.Close()
		out.Close()
		return manifest{}, err
	}

	if err = zw.Close(); err != nil {
		out.Close()
		return manifest{}, err
	}
	if err = out.Close(); err != nil {
		return manifest{}, err
	}
	return m, nil
}

func appendInstaller(stub, zipPath, output string) (string, error) {
	stubBytes, err := embedded.ReadFile(stub)
	if err != nil {
		return "", err
	}
	zf, err := os.Open(zipPath)
	if err != nil {
		return "", err
	}
	defer zf.Close()
	st, err := zf.Stat()
	if err != nil {
		return "", err
	}

	tmp := output + ".tmp"
	out, err := os.Create(tmp)
	if err != nil {
		return "", err
	}
	if _, err = out.Write(stubBytes); err != nil {
		out.Close()
		return "", err
	}
	h := sha256.New()
	if _, err = io.Copy(io.MultiWriter(out, h), zf); err != nil {
		out.Close()
		return "", err
	}
	footer := make([]byte, footerSize)
	copy(footer[:32], payloadMagic[:])
	binary.LittleEndian.PutUint64(footer[32:40], uint64(st.Size()))
	copy(footer[40:72], h.Sum(nil))
	if _, err = out.Write(footer); err != nil {
		out.Close()
		return "", err
	}
	if err = out.Close(); err != nil {
		return "", err
	}
	_ = os.Remove(output)
	if err = os.Rename(tmp, output); err != nil {
		return "", err
	}

	f, err := os.Open(output)
	if err != nil {
		return "", err
	}
	sum := sha256.New()
	_, err = io.Copy(sum, f)
	f.Close()
	if err != nil {
		return "", err
	}
	digest := hex.EncodeToString(sum.Sum(nil))
	checksum := digest + "  " + filepath.Base(output) + "\r\n"
	_ = os.WriteFile(output+".sha256.txt", []byte(checksum), 0644)
	return digest, nil
}

func main() {
	source := defaultInstallDir()
	version := versionFromInstall(source)
	output := defaultOutput(version)
	if len(os.Args) > 1 && strings.TrimSpace(os.Args[1]) != "" {
		source = filepath.Clean(os.Args[1])
		version = versionFromInstall(source)
		output = defaultOutput(version)
	}
	if len(os.Args) > 2 && strings.TrimSpace(os.Args[2]) != "" {
		output = filepath.Clean(os.Args[2])
	}

	fmt.Println("ReelIndex Offline Installer Builder")
	fmt.Println("Source:", source)
	fmt.Println("Output:", output)
	fmt.Println()

	sourceAbs, _ := filepath.Abs(source)
	outputAbs, _ := filepath.Abs(output)
	relOut, _ := filepath.Rel(sourceAbs, outputAbs)
	if relOut == "." || (!strings.HasPrefix(relOut, ".."+string(os.PathSeparator)) && relOut != "..") {
		msg("ReelIndex Offline Installer Builder", "Choose an output path outside the ReelIndex installation directory.", 0x10)
		os.Exit(1)
	}

	if os.Getenv("LOCALAPPDATA") == "" {
		msg("ReelIndex Offline Installer Builder", "LOCALAPPDATA is unavailable.", 0x10)
		os.Exit(1)
	}
	for _, p := range requiredFiles(source) {
		if _, err := os.Stat(p); err != nil {
			msg("ReelIndex Offline Installer Builder", "The installed ReelIndex runtime is incomplete. Missing:\n\n"+p+"\n\nRun the normal installer once on an internet-connected machine, then retry.", 0x10)
			os.Exit(1)
		}
	}
	if _, err := os.Stat(filepath.Join(source, "tools", "mediainfo.exe")); err != nil {
		fmt.Println("Warning: MediaInfo is not installed; the offline package will still include ffprobe and ReelIndex will continue to work.")
	}
	if msg("ReelIndex Offline Installer Builder", "Create a fully offline ReelIndex installer from the installed program files?\n\nIncluded: Python, Python packages, ffprobe, MediaInfo when present, and the ReelIndex application.\n\nExcluded: database, source credentials, posters, scan logs, and all other user data.", 0x44|0x20) != 6 {
		return
	}

	if err := os.MkdirAll(filepath.Dir(output), 0755); err != nil {
		msg("ReelIndex Offline Installer Builder", err.Error(), 0x10)
		os.Exit(1)
	}
	temp, err := os.CreateTemp("", "reelindex-offline-*.zip")
	if err != nil {
		msg("ReelIndex Offline Installer Builder", err.Error(), 0x10)
		os.Exit(1)
	}
	zipPath := temp.Name()
	temp.Close()
	defer os.Remove(zipPath)

	m, err := buildZip(source, zipPath, version)
	if err != nil {
		msg("ReelIndex Offline Installer Builder", "Could not build payload:\n\n"+err.Error(), 0x10)
		os.Exit(1)
	}
	digest, err := appendInstaller("offline-installer-stub.exe", zipPath, output)
	if err != nil {
		msg("ReelIndex Offline Installer Builder", "Could not create installer:\n\n"+err.Error(), 0x10)
		os.Exit(1)
	}
	st, _ := os.Stat(output)
	summary := fmt.Sprintf("Offline installer created successfully.\n\nVersion: %s\nFiles: %d\nPayload size: %.1f MB\nInstaller: %s\nSHA-256: %s\n\nNo database, credentials, posters, or logs were included.", m.Version, m.FileCount, float64(st.Size())/(1024*1024), output, digest)
	fmt.Println(summary)
	msg("ReelIndex Offline Installer Builder", summary, 0x40)
}

var _ = errors.New
