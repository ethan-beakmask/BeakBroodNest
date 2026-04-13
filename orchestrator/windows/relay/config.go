package main

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

type ServerConfig struct {
	Port int    `yaml:"port"`
	Bind string `yaml:"bind"`
}

type AuthConfig struct {
	Token string `yaml:"token"`
}

type MobaXtermConfig struct {
	Path            string `yaml:"path"`
	DefaultBookmark string `yaml:"default_bookmark"`
	DefaultTarget   string `yaml:"default_target"`
}

type Config struct {
	Server    ServerConfig    `yaml:"server"`
	Auth      AuthConfig      `yaml:"auth"`
	MobaXterm MobaXtermConfig `yaml:"mobaxterm"`
}

func DefaultConfig() *Config {
	return &Config{
		Server: ServerConfig{
			Port: 5200,
			Bind: "0.0.0.0",
		},
		MobaXterm: MobaXtermConfig{
			DefaultTarget: "[X390]",
		},
	}
}

func LoadConfig(path string) (*Config, error) {
	cfg := DefaultConfig()

	if !filepath.IsAbs(path) {
		exe, err := os.Executable()
		if err == nil {
			path = filepath.Join(filepath.Dir(exe), path)
		}
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return nil, fmt.Errorf("讀取設定檔 %s 失敗: %w", path, err)
	}

	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("解析設定檔 %s 失敗: %w", path, err)
	}

	return cfg, nil
}
