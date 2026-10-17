# Ollama Vulkan runtime

The application uses Ollama's native `/api/chat` endpoint when
`LLM_PROVIDER=ollama`. It passes the host CPU thread count through
`num_thread`, and deliberately leaves `num_gpu` unset so Ollama can offload to
an available GPU and fall back to a multithreaded CPU automatically.

Run the Ollama daemon with Vulkan selected:

```sh
export OLLAMA_VULKAN=1
ollama serve
```

Do not set CUDA or ROCm library overrides. Leaving GPU layer selection unset
lets Ollama use the Vulkan device when available and choose CPU execution when
it is not.

In another terminal, make sure the downloaded model name matches the setting:

```sh
ollama list
ollama run qwen:4b
```

For Docker Compose, copy `.env.docker.example` to `.env` and then run
`docker compose up --build`. The backend connects to the host daemon through
`host.docker.internal`; the Vulkan environment variable must be set on the
host Ollama process, not only inside the backend container.

The runtime does not request CUDA or ROCm. If the Vulkan backend cannot find a
compatible GPU, Ollama uses CPU execution and `LLM_NUM_THREADS=0` expands to
all detected host CPU cores. Set `LLM_NUM_THREADS` to a positive value to cap
CPU parallelism.