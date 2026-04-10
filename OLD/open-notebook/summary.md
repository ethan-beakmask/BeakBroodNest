# lfnovo/open-notebook — DeepWiki 摘要

分析時間: 2026-02-04 00:45

# Page: Overview

# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CHANGELOG.md](CHANGELOG.md)
- [CLAUDE.md](CLAUDE.md)
- [frontend/src/components/sources/AddSourceDialog.tsx](frontend/src/components/sources/AddSourceDialog.tsx)
- [frontend/src/components/sources/steps/SourceTypeStep.tsx](frontend/src/components/sources/steps/SourceTypeStep.tsx)
- [open_notebook/domain/CLAUDE.md](open_notebook/domain/CLAUDE.md)
- [open_notebook/utils/CLAUDE.md](open_notebook/utils/CLAUDE.md)
- [open_notebook/utils/chunking.py](open_notebook/utils/chunking.py)
- [pyproject.toml](pyproject.toml)
- [uv.lock](uv.lock)

</details>



Open Notebook is an open-source, privacy-focused AI research assistant that serves as a self-hosted alternative to Google's Notebook LM. It enables users to organize research materials (PDFs, videos, audio, web pages), chat with AI about their content, and generate professional podcasts—all while maintaining complete control over their data and choice of AI providers.

**Version**: 1.6.2 (as of [pyproject.toml:3]())

**Key Differentiators:**
- **Privacy First**: Self-hosted deployment—your research never leaves your infrastructure
- **Multi-Provider AI**: 10+ LLM providers (OpenAI, Anthropic, Ollama, Google, Groq, Mistral, DeepSeek, xAI, OpenRouter, VertexAI) plus specialized services (VoyageAI embeddings, ElevenLabs TTS)
- **No Vendor Lock-in**: Switch providers via environment variables, deploy anywhere, own your data
- **Full API Access**: FastAPI REST API at `/docs` for automation and integration
- **Advanced Podcasts**: Multi-speaker podcast generation with customizable voice profiles and episode templates

**This Page**: Provides a high-level architectural overview and maps user-facing concepts to code entities. For detailed subsystem documentation, see the child pages.

**Sources**: [pyproject.toml:1-43](), Diagram 1 and Diagram 6 from provided system architecture

---

## What Open Notebook Does

Open Notebook helps researchers and knowledge workers organize and interact with their research materials using AI:

| Capability | Description | Implementation |
|------------|-------------|----------------|
| **Multi-Modal Content** | Import PDFs, videos, audio, web pages, Office docs | [content-core](https://github.com/lfnovo/content-core) library in [pyproject.toml:36]() |
| **Notebook Organization** | Organize sources and notes into project notebooks | `Notebook` class in [open_notebook/domain/notebook.py]() |
| **Vector Search** | Semantic search across all content using embeddings | `SourceEmbedding` table in SurrealDB, `fn::vector_search` |
| **AI Chat** | Context-aware conversations powered by RAG | `ChatSession` class, `chat_graph` workflow in [open_notebook/graphs/chat.py]() |