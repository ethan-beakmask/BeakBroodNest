//go:build windows

package main

import (
	"fmt"
	"log"
	"syscall"
	"unsafe"
)

// ---------------------------------------------------------------------------
// 選單 ID
// ---------------------------------------------------------------------------

const (
	idmTogglePause = 1001
	idmLaunchMoba  = 1002
	idmQuit        = 1003
)

// ---------------------------------------------------------------------------
// 全域 tray 狀態（tray 回呼需要存取）
// ---------------------------------------------------------------------------

var (
	gCfg   *Config
	gState *State
	gSrv   *Server
	gHwnd  uintptr
	gNID   notifyIconDataW
)

// ---------------------------------------------------------------------------
// StartTray -- 初始化系統列圖示並啟動訊息迴圈
// ---------------------------------------------------------------------------

func StartTray(cfg *Config, state *State, srv *Server) {
	gCfg = cfg
	gState = state
	gSrv = srv

	hInstance, _, _ := procGetModuleHandleW.Call(0)

	// 註冊視窗類別
	className := utf16Ptr("BeakCortexRelayClass")
	// 從 .exe 資源載入自訂圖示 (resource ID 1)，失敗時 fallback 系統圖示
	hIcon, _, _ := procLoadIconW.Call(hInstance, uintptr(1))
	if hIcon == 0 {
		hIcon, _, _ = procLoadIconW.Call(0, uintptr(idiApplication))
	}
	hCursor, _, _ := procLoadCursorW.Call(0, uintptr(idcArrow))

	wc := wndClassExW{
		Style:         0,
		LpfnWndProc:   syscall.NewCallback(wndProc),
		HInstance:     hInstance,
		HIcon:         hIcon,
		HCursor:       hCursor,
		HbrBackground: 0,
		LpszClassName: className,
		HIconSm:      hIcon,
	}
	wc.CbSize = uint32(unsafe.Sizeof(wc))

	atom, _, err := procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
	if atom == 0 {
		log.Fatalf("RegisterClassExW 失敗: %v", err)
	}

	// 建立隱藏的訊息視窗（位置與大小無關緊要）
	hwnd, _, err := procCreateWindowExW.Call(
		uintptr(wsExToolWindow),
		uintptr(unsafe.Pointer(className)),
		uintptr(unsafe.Pointer(utf16Ptr(appName))),
		0, // style
		0, 0, 0, 0, // x, y, w, h
		0, 0,
		hInstance,
		0,
	)
	if hwnd == 0 {
		log.Fatalf("CreateWindowExW 失敗: %v", err)
	}
	gHwnd = hwnd

	// 新增系統列圖示
	addTrayIcon(hwnd, hIcon)

	log.Println("系統列圖示已建立")

	// 訊息迴圈（阻塞直到 WM_QUIT）
	var m msg
	for {
		ret, _, _ := procGetMessageW.Call(
			uintptr(unsafe.Pointer(&m)),
			0, 0, 0,
		)
		if ret == 0 { // WM_QUIT
			break
		}
		procTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}

	// 清理
	removeTrayIcon()
	procDestroyWindow.Call(hwnd)
}

// ---------------------------------------------------------------------------
// Tray 圖示操作
// ---------------------------------------------------------------------------

func addTrayIcon(hwnd, hIcon uintptr) {
	gNID = notifyIconDataW{}
	gNID.CbSize = uint32(unsafe.Sizeof(gNID))
	gNID.HWnd = hwnd
	gNID.UID = 1
	gNID.UFlags = nifMessage | nifIcon | nifTip
	gNID.UCallbackMessage = wmTrayIcon
	gNID.HIcon = hIcon

	setTip(&gNID, buildTooltip())

	procShell_NotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(&gNID)))
}

func removeTrayIcon() {
	procShell_NotifyIconW.Call(nimDelete, uintptr(unsafe.Pointer(&gNID)))
}

func updateTrayTooltip() {
	setTip(&gNID, buildTooltip())
	procShell_NotifyIconW.Call(nimModify, uintptr(unsafe.Pointer(&gNID)))
}

func buildTooltip() string {
	stats := gState.GetStats()
	status := "執行中"
	if gState.IsPaused() {
		status = "已暫停"
	}
	tip := fmt.Sprintf("%s | %s | 處理:%d 成功:%d 失敗:%d",
		appName, status, stats.Total, stats.Success, stats.Failure)
	if len(tip) > 127 {
		tip = tip[:127]
	}
	return tip
}

func setTip(nid *notifyIconDataW, tip string) {
	tipUTF16, _ := syscall.UTF16FromString(tip)
	for i := range nid.SzTip {
		nid.SzTip[i] = 0
	}
	copy(nid.SzTip[:], tipUTF16)
}

// NotifyStateChanged 由 HTTP handler 呼叫，通知 tray 更新 tooltip
func NotifyStateChanged() {
	if gHwnd != 0 {
		procPostMessageW.Call(gHwnd, wmUpdateTip, 0, 0)
	}
}

// ---------------------------------------------------------------------------
// 右鍵選單
// ---------------------------------------------------------------------------

func showContextMenu(hwnd uintptr) {
	menu, _, _ := procCreatePopupMenu.Call()
	if menu == 0 {
		return
	}

	// 狀態列（不可點擊）
	stats := gState.GetStats()
	statusText := fmt.Sprintf("處理: %d  成功: %d  失敗: %d", stats.Total, stats.Success, stats.Failure)
	appendMenu(menu, mfString|mfGrayed, 0, statusText)
	appendMenu(menu, mfSeparator, 0, "")

	// 暫停/恢復
	if gState.IsPaused() {
		appendMenu(menu, mfString, idmTogglePause, "恢復接收")
	} else {
		appendMenu(menu, mfString, idmTogglePause, "暫停接收")
	}

	appendMenu(menu, mfSeparator, 0, "")

	// 啟動 MobaXterm
	if gCfg.MobaXterm.Path != "" {
		appendMenu(menu, mfString, idmLaunchMoba, "啟動 MobaXterm")
	} else {
		appendMenu(menu, mfString|mfGrayed, idmLaunchMoba, "啟動 MobaXterm (未設定路徑)")
	}

	appendMenu(menu, mfSeparator, 0, "")
	appendMenu(menu, mfString, idmQuit, "結束")

	// 顯示選單
	var pt point
	procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	procSetForegroundWindow.Call(hwnd)

	procTrackPopupMenu.Call(
		menu,
		uintptr(tpmBottomAlign|tpmLeftAlign),
		uintptr(pt.X), uintptr(pt.Y),
		0, hwnd, 0,
	)

	procDestroyMenu.Call(menu)
}

func appendMenu(menu uintptr, flags, id uint32, text string) {
	procAppendMenuW.Call(menu, uintptr(flags), uintptr(id), uintptr(unsafe.Pointer(utf16Ptr(text))))
}

// ---------------------------------------------------------------------------
// 視窗回呼函式
// ---------------------------------------------------------------------------

func wndProc(hwnd, m, wParam, lParam uintptr) uintptr {
	switch uint32(m) {
	case wmTrayIcon:
		switch uint32(lParam) {
		case wmRButtonUp:
			showContextMenu(hwnd)
		}
		return 0

	case wmUpdateTip:
		updateTrayTooltip()
		return 0

	case wmCommand:
		switch uint32(wParam & 0xFFFF) {
		case idmTogglePause:
			paused := gState.TogglePause()
			if paused {
				log.Println("已暫停接收")
			} else {
				log.Println("已恢復接收")
			}
			updateTrayTooltip()

		case idmLaunchMoba:
			go func() {
				err := LaunchMobaXterm(gCfg.MobaXterm.Path, gCfg.MobaXterm.DefaultBookmark)
				if err != nil {
					log.Printf("啟動 MobaXterm 失敗: %v", err)
				}
			}()

		case idmQuit:
			procPostQuitMessage.Call(0)
		}
		return 0

	case wmDestroy:
		procPostQuitMessage.Call(0)
		return 0
	}

	ret, _, _ := procDefWindowProcW.Call(hwnd, m, wParam, lParam)
	return ret
}
