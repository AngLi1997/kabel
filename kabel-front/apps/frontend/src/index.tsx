import ReactDOM from 'react-dom/client';
import React from 'react';
import '@kabel/video-annotator-react/dist/style.css';
import '@kabel/audio-annotator-react/dist/style.css';

import './polyfills';
import App from './App';
import './initialize';
import './styles/index.css';

window.React = React;
// 是否是线上演示环境
window.IS_ONLINE = !!import.meta.env.VITE_IS_ONLINE;

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
