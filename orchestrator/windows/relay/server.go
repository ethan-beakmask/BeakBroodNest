package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"
)

type Server struct {
	cfg    *Config
	state  *State
	server *http.Server
}

type RelayRequest struct {
	Action    string `json:"action"`
	Message   string `json:"message"`
	Target    string `json:"target"`
	Source    string `json:"source"`
	Timestamp string `json:"timestamp"`
}

type LaunchRequest struct {
	Bookmark string `json:"bookmark"`
}

func NewServer(cfg *Config, state *State) *Server {
	s := &Server{cfg: cfg, state: state}

	mux := http.NewServeMux()
	mux.HandleFunc("/relay", s.handleRelay)
	mux.HandleFunc("/status", s.handleStatus)
	mux.HandleFunc("/launch", s.handleLaunch)

	s.server = &http.Server{
		Addr:         fmt.Sprintf("%s:%d", cfg.Server.Bind, cfg.Server.Port),
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	return s
}

func (s *Server) Start() {
	addr := s.server.Addr
	log.Printf("HTTP server 啟動: %s", addr)
	if err := s.server.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("HTTP server 錯誤: %v", err)
	}
}

func (s *Server) Stop() {
	s.server.Close()
}

func (s *Server) handleRelay(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		jsonError(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req RelayRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		jsonError(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	if s.state.IsPaused() {
		jsonResp(w, map[string]string{
			"status":       "paused",
			"action_taken": "rejected (server paused)",
		})
		return
	}

	target := req.Target
	if target == "" {
		target = s.cfg.MobaXterm.DefaultTarget
	}

	var result string
	var success bool

	switch req.Action {
	case "paste":
		result, success = s.doPaste(req.Message, target)
	case "notify":
		result = fmt.Sprintf("logged: %s", req.Message)
		success = true
		log.Printf("[NOTIFY] source=%s | %s", req.Source, req.Message)
	case "clipboard":
		result = "clipboard action not supported in Go version, use paste"
		success = false
	default:
		result = fmt.Sprintf("unknown action: %s", req.Action)
		success = false
	}

	preview := req.Message
	if len(preview) > 100 {
		preview = preview[:100]
	}
	s.state.RecordMessage(req.Action, req.Source, target, preview, result, success)
	NotifyStateChanged()

	jsonResp(w, map[string]string{"status": "received", "action_taken": result})
}

func (s *Server) doPaste(message, target string) (string, bool) {
	result, err := PasteToMobaXterm(message, target)
	if err != nil {
		log.Printf("[PASTE] 失敗: %v", err)
		return fmt.Sprintf("paste failed: %v", err), false
	}
	log.Printf("[PASTE] 成功: %s", result)
	return result, true
}

func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		jsonError(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	stats := s.state.GetStats()
	status := "running"
	if s.state.IsPaused() {
		status = "paused"
	}

	jsonResp(w, map[string]interface{}{
		"status":          status,
		"server_time":     time.Now().Format("2006-01-02 15:04:05"),
		"uptime":          s.state.Uptime(),
		"stats":           stats,
		"recent_messages": s.state.GetRecent(),
		"mobaxterm_path":  s.cfg.MobaXterm.Path,
	})
}

func (s *Server) handleLaunch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		jsonError(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req LaunchRequest
	json.NewDecoder(r.Body).Decode(&req)

	bookmark := req.Bookmark
	if bookmark == "" {
		bookmark = s.cfg.MobaXterm.DefaultBookmark
	}

	if s.cfg.MobaXterm.Path == "" {
		jsonError(w, "mobaxterm.path 未設定", http.StatusBadRequest)
		return
	}

	err := LaunchMobaXterm(s.cfg.MobaXterm.Path, bookmark)
	if err != nil {
		log.Printf("[LAUNCH] 失敗: %v", err)
		jsonError(w, fmt.Sprintf("啟動失敗: %v", err), http.StatusInternalServerError)
		return
	}

	log.Printf("[LAUNCH] MobaXterm 已啟動, bookmark=%s", bookmark)
	jsonResp(w, map[string]string{"status": "launched", "bookmark": bookmark})
}

func jsonResp(w http.ResponseWriter, data interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(data)
}

func jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"status": "error", "reason": msg})
}
