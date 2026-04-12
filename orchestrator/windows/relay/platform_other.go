//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

func PasteToMobaXterm(text, target string) (string, error) {
	return "", fmt.Errorf("僅支援 Windows 平台")
}

func LaunchMobaXterm(path, bookmark string) error {
	return fmt.Errorf("僅支援 Windows 平台")
}

func NotifyStateChanged() {}

func StartTray(cfg *Config, state *State, srv *Server) {
	// 非 Windows：以 console 模式運行，等待 signal 結束
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
}
