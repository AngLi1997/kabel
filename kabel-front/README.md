# Kabel 前端

Kabel 前端是基于 React、TypeScript 和 Vite 的多模态标注应用，同时包含图片、音频和视频标注组件。

## 启动

```bash
pnpm install
pnpm dev
```

开发地址：<http://localhost:3004>

Vite 默认把 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8002`，请先启动 Kabel 后端。

## 构建与检查

```bash
pnpm build
pnpm build:frontend
```

更多完整说明请查看项目根目录的 `README.md`。
