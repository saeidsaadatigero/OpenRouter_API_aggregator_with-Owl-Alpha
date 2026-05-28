
# OpenRouter API Aggregator with Owl-Alpha

A structured, clean-architecture Python implementation for integrating OpenRouter's API aggregator utilizing the high-performance `openrouter/owl-alpha` and `tencent/hy3-preview` models. Built with strict OOP, Service Layer pattern, and type hinting.

## Features
- **Service Layer Architecture**: Decoupled LLM business logic from entrypoints.
- **Strict Typing**: Full Python type hints for robust development.
- **Environment Safety**: Zero hardcoded secrets using `python-decouple`.

## Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/saeidsaadatigero/OpenRouter_API_aggregator_with-Owl-Alpha.git](https://github.com/saeidsaadatigero/OpenRouter_API_aggregator_with-Owl-Alpha.git)
   cd OpenRouter_API_aggregator_with-Owl-Alpha

```

2. Install dependencies:
```bash
pip install openai python-decouple

```


3. Configure environment variables. Create a `.env` file in the root directory:
https://openrouter.ai/
```env
OPENROUTER_API_KEY=your_openrouter_api_key_here

```



## Usage

Run the main execution pipeline:

```bash
python main.py

```