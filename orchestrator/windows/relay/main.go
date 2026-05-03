package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime"
)

const (
	appName    = "BeakBroodNest Relay"
	appVersion = "1.2.1"
)

func main() {
	// Windows tray message pump 必須綁定 OS thread
	runtime.LockOSThread()

	var (
		configPath string
		showHelp   bool
	)
	flag.StringVar(&configPath, "config", "config.yaml", "設定檔路徑")
	flag.BoolVar(&showHelp, "help", false, "顯示使用說明")
	flag.Parse()

	if showHelp {
		printUsage()
		os.Exit(0)
	}

	// 設定 log 輸出到檔案（與執行檔同目錄）
	logPath := resolveRelPath("BeakBroodNest.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "無法開啟 log 檔 %s: %v\n", logPath, err)
		os.Exit(1)
	}
	defer logFile.Close()
	log.SetOutput(logFile)
	log.SetFlags(log.Ldate | log.Ltime)

	cfg, err := LoadConfig(configPath)
	if err != nil {
		log.Fatalf("設定檔錯誤: %v", err)
	}

	state := NewState()
	srv := NewServer(cfg, state)
	go srv.Start()

	log.Printf("%s v%s 啟動 | HTTP %s:%d", appName, appVersion, cfg.Server.Bind, cfg.Server.Port)

	// StartTray 阻塞直到使用者結束程式
	// Windows: tray message pump, 其他: 等待 signal
	StartTray(cfg, state, srv)

	srv.Stop()
	log.Println("已關閉")
}

// resolveRelPath 將相對路徑解析為相對於執行檔目錄的絕對路徑
func resolveRelPath(name string) string {
	exe, err := os.Executable()
	if err != nil {
		return name
	}
	return filepath.Join(filepath.Dir(exe), name)
}

func printUsage() {
	fmt.Printf(`%s v%s -- Windows 系統列常駐 Relay Receiver

端點：
  POST /relay    接收 orchestrator 指令（paste/notify/clipboard）
  GET  /status   查詢狀態與統計資訊
  POST /launch   啟動 MobaXterm

選項：
  --config 路徑  指定設定檔（預設同目錄 config.yaml）
  --help         顯示此說明後結束

Log 檔案：同目錄 BeakBroodNest.log
`, appName, appVersion)
}
