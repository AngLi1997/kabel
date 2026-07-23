# Development Guide

## Setup development environment

### Setup latest backend server

search kabel in [Test Pypi](https://test.pypi.org/), to find the right version for installation.

```bash
# change version '0.1.220' to the version you need.
pip install -i https://test.pypi.org/simple/ kabel==1.0.6a5
kabel --help
kabel --port 8000
```

### Setup frontend environment

```bash
npm install

# edit proxy configuration in need.
vim vite.config.js

npm run start

open http://localhost:3000/
```
