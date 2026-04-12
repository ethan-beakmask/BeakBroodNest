//go:build windows

package main

import (
	"fmt"
	"log"
	"os/exec"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// ---------------------------------------------------------------------------
// Win32 DLL + Proc 宣告
// ---------------------------------------------------------------------------

var (
	user32DLL   = syscall.NewLazyDLL("user32.dll")
	shell32DLL  = syscall.NewLazyDLL("shell32.dll")
	kernel32DLL = syscall.NewLazyDLL("kernel32.dll")
)

var (
	// 視窗列舉與資訊
	procEnumWindows         = user32DLL.NewProc("EnumWindows")
	procEnumChildWindows    = user32DLL.NewProc("EnumChildWindows")
	procGetWindowTextW      = user32DLL.NewProc("GetWindowTextW")
	procGetClassNameW       = user32DLL.NewProc("GetClassNameW")
	procIsWindowVisible     = user32DLL.NewProc("IsWindowVisible")

	// 視窗控制
	procSetForegroundWindow = user32DLL.NewProc("SetForegroundWindow")
	procShowWindow          = user32DLL.NewProc("ShowWindow")
	procSendMessageW        = user32DLL.NewProc("SendMessageW")
	procPostMessageW        = user32DLL.NewProc("PostMessageW")

	// 鍵盤模擬
	procKeybdEvent = user32DLL.NewProc("keybd_event")

	// Tray icon
	procShell_NotifyIconW = shell32DLL.NewProc("Shell_NotifyIconW")

	// 視窗類別 / 訊息迴圈
	procRegisterClassExW = user32DLL.NewProc("RegisterClassExW")
	procCreateWindowExW  = user32DLL.NewProc("CreateWindowExW")
	procDefWindowProcW   = user32DLL.NewProc("DefWindowProcW")
	procGetMessageW      = user32DLL.NewProc("GetMessageW")
	procTranslateMessage = user32DLL.NewProc("TranslateMessage")
	procDispatchMessageW = user32DLL.NewProc("DispatchMessageW")
	procPostQuitMessage  = user32DLL.NewProc("PostQuitMessage")
	procLoadIconW        = user32DLL.NewProc("LoadIconW")
	procLoadCursorW      = user32DLL.NewProc("LoadCursorW")
	procDestroyWindow    = user32DLL.NewProc("DestroyWindow")

	// 選單
	procCreatePopupMenu = user32DLL.NewProc("CreatePopupMenu")
	procAppendMenuW     = user32DLL.NewProc("AppendMenuW")
	procTrackPopupMenu  = user32DLL.NewProc("TrackPopupMenu")
	procDestroyMenu     = user32DLL.NewProc("DestroyMenu")
	procGetCursorPos    = user32DLL.NewProc("GetCursorPos")

	// 模組
	procGetModuleHandleW = kernel32DLL.NewProc("GetModuleHandleW")
)

// ---------------------------------------------------------------------------
// Win32 常數
// ---------------------------------------------------------------------------

const (
	// 視窗訊息
	wmApp            = 0x8000
	wmCommand        = 0x0111
	wmDestroy        = 0x0002
	wmChar           = 0x0102
	wmRButtonUp      = 0x0205
	wmLButtonDblClk  = 0x0203
	wmClose          = 0x0010

	// 自訂訊息
	wmTrayIcon  = wmApp + 1
	wmUpdateTip = wmApp + 2

	// 視窗樣式
	wsExToolWindow = 0x00000080

	// ShowWindow
	swRestore = 9

	// Shell_NotifyIcon
	nimAdd    = 0
	nimModify = 1
	nimDelete = 2

	nifMessage = 0x01
	nifIcon    = 0x02
	nifTip     = 0x04

	// 系統圖示
	idiApplication = 32512
	idcArrow       = 32512

	// 選單
	mfString    = 0x0000
	mfSeparator = 0x0800
	mfGrayed    = 0x0001

	tpmBottomAlign = 0x0020
	tpmLeftAlign   = 0x0000

	// 鍵盤
	keyeventfKeyUp = 0x0002
	vkControl      = 0x11
	vkTab          = 0x09
)

// ---------------------------------------------------------------------------
// Win32 結構體
// ---------------------------------------------------------------------------

type point struct {
	X, Y int32
}

type msg struct {
	Hwnd    uintptr
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Pt      point
}

type wndClassExW struct {
	CbSize        uint32
	Style         uint32
	LpfnWndProc   uintptr
	CbClsExtra    int32
	CbWndExtra    int32
	HInstance     uintptr
	HIcon         uintptr
	HCursor       uintptr
	HbrBackground uintptr
	LpszMenuName  *uint16
	LpszClassName *uint16
	HIconSm      uintptr
}

type notifyIconDataW struct {
	CbSize           uint32
	HWnd             uintptr
	UID              uint32
	UFlags           uint32
	UCallbackMessage uint32
	HIcon            uintptr
	SzTip            [128]uint16
	DwState          uint32
	DwStateMask      uint32
	SzInfo           [256]uint16
	UVersion         uint32
	SzInfoTitle      [64]uint16
	DwInfoFlags      uint32
	GuidItem         [16]byte
	HBalloonIcon     uintptr
}

// ---------------------------------------------------------------------------
// 基礎 Win32 包裝函式
// ---------------------------------------------------------------------------

func utf16Ptr(s string) *uint16 {
	p, _ := syscall.UTF16PtrFromString(s)
	return p
}

func getWindowText(hwnd uintptr) string {
	buf := make([]uint16, 512)
	procGetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), 512)
	return syscall.UTF16ToString(buf)
}

func getClassName(hwnd uintptr) string {
	buf := make([]uint16, 256)
	procGetClassNameW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), 256)
	return syscall.UTF16ToString(buf)
}

func isWindowVisible(hwnd uintptr) bool {
	ret, _, _ := procIsWindowVisible.Call(hwnd)
	return ret != 0
}

func setForegroundWindow(hwnd uintptr) {
	procSetForegroundWindow.Call(hwnd)
}

func showWindowCmd(hwnd uintptr, cmd int) {
	procShowWindow.Call(hwnd, uintptr(cmd))
}

func sendMessageW(hwnd uintptr, m uint32, wParam, lParam uintptr) uintptr {
	ret, _, _ := procSendMessageW.Call(hwnd, uintptr(m), wParam, lParam)
	return ret
}

func keybdEvent(vk byte, flags uint32) {
	procKeybdEvent.Call(uintptr(vk), 0, uintptr(flags), 0)
}

func sendCtrlTab() {
	keybdEvent(vkControl, 0)
	keybdEvent(vkTab, 0)
	keybdEvent(vkTab, keyeventfKeyUp)
	keybdEvent(vkControl, keyeventfKeyUp)
}

// ---------------------------------------------------------------------------
// 視窗列舉
// ---------------------------------------------------------------------------

func enumWindows(callback func(hwnd uintptr) bool) {
	cb := syscall.NewCallback(func(hwnd, lparam uintptr) uintptr {
		if callback(hwnd) {
			return 1
		}
		return 0
	})
	procEnumWindows.Call(cb, 0)
}

func enumChildWindows(parent uintptr, callback func(hwnd uintptr) bool) {
	cb := syscall.NewCallback(func(hwnd, lparam uintptr) uintptr {
		if callback(hwnd) {
			return 1
		}
		return 0
	})
	procEnumChildWindows.Call(parent, cb, 0)
}

// ---------------------------------------------------------------------------
// MobaXterm 視窗控制
// ---------------------------------------------------------------------------

func findMobaXterm() (uintptr, string) {
	var found uintptr
	var title string

	enumWindows(func(hwnd uintptr) bool {
		if !isWindowVisible(hwnd) {
			return true // continue
		}
		t := getWindowText(hwnd)
		c := getClassName(hwnd)
		tl := strings.ToLower(t)
		cl := strings.ToLower(c)
		if strings.Contains(tl, "mobaxterm") || strings.Contains(cl, "tmobaxterm") {
			found = hwnd
			title = t
			return false // stop
		}
		return true
	})

	return found, title
}

func findCMoTTY(parent uintptr) uintptr {
	var found uintptr

	enumChildWindows(parent, func(hwnd uintptr) bool {
		cls := getClassName(hwnd)
		if cls == "CMoTTY" && isWindowVisible(hwnd) {
			found = hwnd
			return false
		}
		return true
	})

	return found
}

func switchToTarget(hwnd uintptr, target string, maxAttempts int) bool {
	targetLower := strings.ToLower(target)

	title := getWindowText(hwnd)
	if strings.Contains(strings.ToLower(title), targetLower) {
		return true
	}

	for i := 0; i < maxAttempts; i++ {
		sendCtrlTab()
		time.Sleep(300 * time.Millisecond)
		title = getWindowText(hwnd)
		if strings.Contains(strings.ToLower(title), targetLower) {
			log.Printf("找到目標分頁 %q (第 %d 次切換)", target, i+1)
			return true
		}
	}

	return false
}

func sendCharsToWindow(hwnd uintptr, text string) {
	for _, ch := range text {
		sendMessageW(hwnd, wmChar, uintptr(ch), 0)
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(100 * time.Millisecond)
	sendMessageW(hwnd, wmChar, uintptr('\r'), 0)
}

// PasteToMobaXterm 找到 MobaXterm 視窗，切換到目標分頁，用 WM_CHAR 逐字送入
func PasteToMobaXterm(text, target string) (string, error) {
	hwnd, _ := findMobaXterm()
	if hwnd == 0 {
		return "", fmt.Errorf("找不到 MobaXterm 視窗")
	}

	showWindowCmd(hwnd, swRestore)
	setForegroundWindow(hwnd)
	time.Sleep(300 * time.Millisecond)

	if !switchToTarget(hwnd, target, 10) {
		return "", fmt.Errorf("找不到含 %q 的分頁 (已嘗試 10 次)", target)
	}

	cmotty := findCMoTTY(hwnd)
	if cmotty == 0 {
		return "", fmt.Errorf("找不到 CMoTTY 控件")
	}

	sendCharsToWindow(cmotty, text)

	return fmt.Sprintf("WM_CHAR 已送出, target=%s, len=%d", target, len(text)), nil
}

// LaunchMobaXterm 啟動 MobaXterm 程序
func LaunchMobaXterm(path, bookmark string) error {
	if path == "" {
		return fmt.Errorf("MobaXterm 路徑未設定")
	}

	var cmd *exec.Cmd
	if bookmark != "" {
		cmd = exec.Command(path, "-bookmark", bookmark)
	} else {
		cmd = exec.Command(path)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("啟動 MobaXterm 失敗: %w", err)
	}

	log.Printf("MobaXterm 已啟動: bookmark=%s", bookmark)
	return nil
}
