# Plan JSON 参考

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | 否 | 诗题，显示在顶部 |
| `author` | 否 | 作者，显示在标题下方 |
| `lines` | 是 | 诗句数组，每项一行；也可用 `text` 传带换行的字符串 |
| `new_phrase` | 是 | 底部重排后的新句；也可用 `target_phrase` |
| `punch` | 否 | 显式挖字位置；省略时按 `new_phrase` 自动匹配 |
| `traditional` | 否 | 是否转繁体，默认 `true`；要简体时设 `false` |
| `font_style` | 否 | `old-song`（默认）、`serif`、`kai`、`sans` |
| `font_path` | 否 | 自定义字体文件路径，优先于 `font_style` |
| `palette` | 否 | 配色名或 `{paper, accent, ink}` 对象，默认 `vermilion` |
| `canvas` | 否 | `[宽, 高]`，默认 `[1800, 2400]` |
| `footer` | 否 | 底部小字；传 `null` 或 `false` 可关闭 |
| `seed` | 否 | 扫描纸纹取样偏移和拼贴的随机种子，默认 42；同一输入逐像素复现 |
| `collage` | 否 | 拼贴参数 `{jitter, rotation, roughness}`，控制纸片偏移、旋转和撕边幅度 |

## 字体

`font_style: "old-song"` 的查找顺序：

1. skill 内置的 `assets/fonts/Huiwenmincho-improved.ttf`（汇文明朝体，CC0）
2. 本机安装的京华老宋体 / 汇文明朝体（按常见文件名自动扫描）
3. Noto Serif SC / MingLiU / SimSun 等系统宋体

`font_path` 可以直接指定一个 TTF/OTF/TTC 文件，适合用户自己有京华老宋体或其他古籍字体的情况。

默认 `traditional: true`，脚本会用 Windows 的简繁转换把标题、诗句和新句转成繁体。显式 `punch` 的 `line/index` 指向转换后的最终文本；如果位置是按简体原文数的，建议改用 `new_phrase` 自动匹配，或设 `traditional: false`。

## 自动匹配

省略 `punch` 时，脚本会：

1. 从 `new_phrase` 取出所有汉字；
2. 在诗中找到这些字的出现位置；
3. 优先选稀有字，并尽量把孔分散到不同行、避免相邻字连续被挖；
4. 如果某个字数量不够，直接报错并提示缺哪个字。

新句里的标点会显示在底部，但自动匹配只挖汉字。需要连标点一起挖时，用显式 `punch`。

## 显式 punch

`line` 是行号，`index` 是该行第几个字符，二者都从 0 开始，`index` 包含标点。

```json
{
  "title": "过零丁洋",
  "author": "文天祥",
  "lines": [
    "辛苦遭逢起一经，干戈寥落四周星。",
    "山河破碎风飘絮，身世浮沉雨打萍。",
    "惶恐滩头说惶恐，零丁洋里叹零丁。",
    "人生自古谁无死，留取丹心照汗青。"
  ],
  "new_phrase": "生照山河，死落零丁。",
  "traditional": true,
  "font_style": "old-song",
  "punch": [
    {"line": 0, "index": 11},
    {"line": 1, "index": 0},
    {"line": 1, "index": 1},
    {"line": 2, "index": 8},
    {"line": 2, "index": 14},
    {"line": 3, "index": 1},
    {"line": 3, "index": 6},
    {"line": 3, "index": 12}
  ],
  "palette": "vermilion"
}
```

上面这组位置就是 `过零丁洋` 的示例：残诗为

```text
辛苦遭逢起一经，干戈寥□四周星。
□□破碎风飘絮，身世浮沉雨打萍。
惶恐滩头说惶恐，□丁洋里叹零□。
人□自古谁无□，留取丹心□汗青。
```

## 配色

| 名称 | 纸色 | 孔/底纸 | 墨色 |
|---|---|---|---|
| `vermilion` | 米白 `#F2E8D5` | 朱红 `#A61B1B` | `#2B2B2B` |
| `ink-green` | 米色 `#E9E3D2` | 墨绿 `#2F4F3A` | `#1F2A22` |
| `navy` | 米白 `#EFE6D8` | 藏青 `#1F3A5F` | `#1B2430` |
| `black` | 米色 `#E9E3D6` | 近黑 `#1A1A1A` | `#111111` |
| `ochre` | 米黄 `#F4E9D0` | 赭石 `#B5651D` | `#2B2118` |

自定义：

```json
"palette": {
  "paper": "#F1E7D4",
  "accent": "#7A1F1F",
  "ink": "#222222"
}
```

## 拼贴

底部每个汉字是一张单独的纸片，默认带很轻的手撕毛边，并且不做机械对齐：

```json
"collage": {
  "jitter": 3.2,
  "rotation": 1.1,
  "roughness": 2.2
}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `jitter` | `3.2` | 纸片中心相对网格位置的最大偏移（px，按 1800px 宽画布计，其他尺寸自动缩放） |
| `rotation` | `1.1` | 纸片的最大旋转角度（度） |
| `roughness` | `2.2` | 撕边起伏的幅度（px，同样随画布缩放） |

想要完全整齐的排版，设为 `{"jitter": 0, "rotation": 0, "roughness": 0}`。`roughness` 为 0 时纸片仍是直角纸片，但不再有撕边起伏。

## 命令

```bash
# 只检查，不出图
python scripts/render_punch_poem.py plan.json --check

# 出图
python scripts/render_punch_poem.py plan.json -o outputs/poem-punch.png

# 内置示例
python scripts/render_punch_poem.py --demo -o outputs/demo.png
```

## 常见错误

| 错误 | 处理 |
|---|---|
| `诗中「X」只有 N 个` | 新句里有诗中没有的字，换字或换诗 |
| `punch 与新句汉字不一致` | 显式位置挖出的字和新句对不上，检查 `line/index` |
| `繁体转换改变了字符数` | 显式位置会错位；改用 `new_phrase` 自动匹配，或设 `traditional: false` |
| `诗句太长，字号会小于 24px` | 把长句拆成更多行，或缩短选段 |
| `没有找到可用的中文字体` | 检查 `assets/fonts/` 是否完整，或用 `font_path` 指定字体文件 |

## 纸张与拼贴

- 上方使用随包附带的 `assets/textures/ricepaper.png` 米纸扫描纹理，保留真实纤维与细微纸浆起伏；灰度化并归一化后按原有纸色着色，不加污迹、重斑驳或模拟帘纹
- 纹理按画布宽度等比例缩放并无缝平铺，不把整张小图直接拉伸到画布；`seed` 决定取样偏移
- 下方色纸使用同一扫描纹理，但明暗起伏比上方克制，避免和诗句抢注意力
- 两纸交界处有一道很浅的接触投影，让上方纸张看起来是叠放在下方色纸上
- 下方汉字纸片从上方纸面取样，因此保留同一套纤维和色调；每张纸片有极轻微的明度差、尺寸差、位置偏移和旋转
- `seed` 会改变纸纹取样位置和拼贴偏移；同一输入可逐像素复现同一张图片
- 素材缺失或损坏时明确报错，不静默退回纯色或程序噪声；完整来源与 CC BY-SA 3.0 授权见 `assets/textures/NOTICE.md`
- 生成 PNG 内嵌纹理署名、来源、授权和修改说明；会剥离元数据的平台应在随图说明中保留这些信息
