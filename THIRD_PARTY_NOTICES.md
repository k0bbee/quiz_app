# Third-Party Notices

本文件记录AI课程刷题软件的直接Python依赖和重要外部运行时。它用于区分项目原创源程序与第三方组件，不替代组件随附的完整许可证文本，也不表示项目拥有这些组件的著作权。

## 版本口径

`requirements.txt`目前声明最低兼容版本而非锁定版本。下表“审计环境版本”来自2026年7月23日实际测试环境，仅用于当前审计；制作V1.0.0发布包和软件著作权材料时，必须从冻结环境重新生成版本与许可证清单。

| 组件 | 审计环境版本 | 项目用途 | 许可证/授权模式 | 官方来源 |
|---|---:|---|---|---|
| PyQt6 | 6.11.0 | 桌面用户界面、信号和工作线程 | GPL-3.0-only；如另行购买则可适用Riverbank商业许可 | [Riverbank PyQt](https://www.riverbankcomputing.com/software/pyqt/) |
| PyQt6-Qt6 | 6.11.1 | PyQt wheel携带的Qt运行库 | 当前包元数据标注LGPL-3.0 | [Qt开源许可](https://www.qt.io/licensing/open-source-lgpl-obligations) |
| PyQt6-sip | 13.11.1 | PyQt绑定运行支持 | BSD-2-Clause | [Python-SIP](https://github.com/Python-SIP/sip) |
| requests | 2.33.1 | LLM与用户主动发起的联网请求 | Apache-2.0 | [Requests LICENSE](https://github.com/psf/requests/blob/main/LICENSE) |
| keyring | 25.7.0 | 操作系统安全凭据存储 | MIT | [keyring LICENSE](https://github.com/jaraco/keyring/blob/main/LICENSE) |
| pypdfium2 | 5.10.1 | PDF文本提取和扫描页渲染 | pypdfium2主体为Apache-2.0或BSD-3-Clause；PDFium为BSD风格许可，二进制分发还须随附PDFium及其依赖许可证 | [pypdfium2许可说明](https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing) |
| Pillow | >=12.3.0 (audited floor) | OCR图像转换 | MIT-CMU | [Pillow LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| pytesseract | 0.3.13 | 调用本机Tesseract OCR | Apache-2.0 | [pytesseract LICENSE](https://github.com/madmaze/pytesseract/blob/master/LICENSE) |
| Tesseract OCR（可选外部程序） | 5.4.0.20240606 | 扫描版PDF的中英文OCR fallback | Apache-2.0；独立安装可能包含Leptonica等其他第三方库 | [Tesseract LICENSE](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE) |

## 直接依赖覆盖

当前 `requirements.txt` 中的全部直接依赖均已在上表列出：PyQt6、requests、keyring、pypdfium2、Pillow和pytesseract。PyQt6-Qt6、PyQt6-sip和Tesseract因其对实际运行或分发边界重要而一并列示。

Python标准库不是随本仓库再许可的第三方包。应用通过标准ZIP/XML处理读取PPTX和DOCX，目前不以python-pptx或python-docx作为运行时依赖。

## 分发与软著边界

- 软件著作权源程序鉴别材料只收录项目原创代码；上述组件的源码、二进制和许可证文本不作为项目自有源程序申报。
- 当前根许可证为GPL-3.0-only，与实际分发包的全部义务不是同一概念。pypdfium2消除了原PDF运行时的强Copyleft依赖，但打包其PDFium二进制时仍须保留并随包提供wheel内列明的PDFium及传递依赖许可证。
- 如果发布安装包，应从冻结构建环境生成完整的直接及传递依赖清单，并随包保留各组件要求的许可证、NOTICE、源码提供方式或替换/重链接说明。
- 如果仅要求用户自行安装Tesseract，应在用户手册中说明其为可选外部程序；如果将其打包，则还要清点Tesseract安装包携带的传递库和语言数据许可证。
