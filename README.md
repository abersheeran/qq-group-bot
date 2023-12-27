# qq-group-bot

QQ 群聊机器人

## 使用

到 [QQ 开放平台](https://q.qq.com) 申请企业账号后，创建一个机器人，获取机器人 ID 和令牌。在 `docker-compose.yml` 同级目录下创建 `.env` 文件，内容如下：

```env
BOT_ID=123456789
BOT_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

使用 `docker-compose up --build -d` 启动。

### Gemini

内置 Gemini-Pro 接口支持，自行申请 KEY 并在 `.env` 中新增一行 `GEMINI_PRO_KEY=xxxxxx`。

如果你需要使用 Gemini 代理服务，在 `.env` 中添加：

```yml
GEMINI_PRO_URL=https://gemini.proxy/v1beta/models/gemini-pro:generateContent
GEMINI_PRO_VISION_URL=https://gemini.proxy/v1beta/models/gemini-pro-vision:generateContent
```

## 二次开发

由于默认的功能非常少，所以二次开发是无可避免的。按照自己的需要修改 `main.py` 中的内容即可。

`qqgroupbot` 目录中的文件是一些封装好的函数，欢迎任何人发起 Pull Request。
