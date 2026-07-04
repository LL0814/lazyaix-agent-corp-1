请直接修改当前项目中"/Users/siqiyang/code_47/lazyaix-agent-corp-1/agent.py"的关于Model类的这段 `try/except` 代码，不需要新增 `model_loader.py` 或调整其他模块。

我的需求是：

1. 先尝试执行 `from models import Model`，以后同事提供真实的 `models.Model` 后，项目应自动优先使用它。
2. 当前项目中还没有真实的 `models` 模块，因此导入失败时，继续使用 `except` 下面定义的备用 `Model` 类。
3. 请把备用 `Model` 从原来只返回模拟字符串的 Stub，改成能够真正调用我自己的临时 LLM。
4. 临时 LLM 使用 OpenAI 兼容接口，通过环境变量读取：

   * `MODEL_API_KEY`
   * `MODEL_BASE_URL`
   * `MODEL_NAME`
5. 使用 `OpenAI(api_key=..., base_url=...)` 创建客户端，在 `complete(prompt: str) -> str` 中调用 `client.chat.completions.create()`，传入用户 prompt，并返回 `response.choices[0].message.content`。
6. 保持对外接口不变，其他模块仍然通过以下方式调用：

   ```python
   model = Model()
   result = model.complete(prompt)
   ```
7. 增加必要的配置校验。如果 API Key、Base URL 或模型名称未配置，要抛出清晰的错误提示；如果模型返回内容为空，也要给出明确错误。
8. 不要使用宽泛的 `except ImportError` 隐藏 `models.py` 内部的依赖错误。建议使用 `except ModuleNotFoundError as exc`，并且只有在确实找不到 `models` 模块时才启用备用 `Model`；如果是 `models.py` 内部缺少其他依赖，则继续抛出原异常。
9. 检查并补充所需导入，例如 `os`、`load_dotenv` 和 `OpenAI`，并调用 `load_dotenv()`。
10. 修改完成后，请告诉我：

    * 修改了哪个文件
    * 具体改了什么
    * 需要安装哪些依赖
    * `.env` 中需要添加哪些配置
    * 如何运行一个最简单的测试来确认临时 LLM 调用成功

请直接执行代码修改，不要只给出示例。
