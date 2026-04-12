package main

import (
	"sync"
	"time"
)

type MessageRecord struct {
	ReceivedAt string `json:"received_at"`
	Action     string `json:"action"`
	Source     string `json:"source"`
	Target     string `json:"target"`
	Preview    string `json:"message_preview"`
	Result     string `json:"result"`
}

type Stats struct {
	Total   int `json:"total"`
	Success int `json:"success"`
	Failure int `json:"failure"`
}

type State struct {
	mu        sync.RWMutex
	paused    bool
	stats     Stats
	recent    []MessageRecord
	startTime time.Time
}

func NewState() *State {
	return &State{
		recent:    make([]MessageRecord, 0, 20),
		startTime: time.Now(),
	}
}

func (s *State) IsPaused() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.paused
}

func (s *State) TogglePause() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.paused = !s.paused
	return s.paused
}

func (s *State) RecordMessage(action, source, target, preview, result string, success bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.stats.Total++
	if success {
		s.stats.Success++
	} else {
		s.stats.Failure++
	}

	rec := MessageRecord{
		ReceivedAt: time.Now().Format("2006-01-02 15:04:05"),
		Action:     action,
		Source:     source,
		Target:     target,
		Preview:    preview,
		Result:     result,
	}

	if len(s.recent) >= 20 {
		s.recent = s.recent[1:]
	}
	s.recent = append(s.recent, rec)
}

func (s *State) GetStats() Stats {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.stats
}

func (s *State) GetRecent() []MessageRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]MessageRecord, len(s.recent))
	copy(result, s.recent)
	return result
}

func (s *State) Uptime() string {
	return time.Since(s.startTime).Truncate(time.Second).String()
}
