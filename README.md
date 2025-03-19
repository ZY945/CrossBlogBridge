## 1. yuque_hexo 方式

### 主要功能
- 专为Hexo博客系统设计，将语雀文档转换为Hexo博客文章
- 支持文章元数据(front matter)处理
- 支持图片本地化或CDN转换
- 支持增量更新

### API调用流程
1. **初始化客户端**：创建YuqueClient实例，设置token和知识库信息
2. **获取用户文章列表**：调用`/repos/{namespace}/docs`接口
3. **获取目录结构**：调用`/repos/{namespace}/toc`接口，构建文档层级关系
4. **获取文章详情**：对每篇文章调用`/repos/{namespace}/docs/{slug}`接口获取详细内容
5. **处理文章内容**：
   - 解析front matter
   - 处理图片链接
   - 添加基于目录结构的标签
6. **生成Hexo文章**：将处理后的内容写入Hexo博客目录

### 特点
- 更加专注于博客发布
- 支持Hexo的front matter格式
- 支持图片处理
- 有缓存机制，支持增量更新

## 2. app.py + yuque_backups + yuque_local 方式

### 主要功能
- 更通用的备份工具，专注于文档备份
- 保持原始文档结构
- 可能支持更多语雀功能(如评论等)

### API调用流程
1. **初始化Token**：设置API请求头
2. **获取用户ID**：调用`/user`接口
3. **获取知识库列表**：调用`/users/{user_id}/repos`接口
4. **获取知识库目录结构**：调用`/repos/{repo_id}/toc`接口
5. **递归遍历目录结构**：
   - 构建与语雀相同的目录结构
   - 对每个文档节点调用`/repos/{repo_id}/docs/{doc_id}`获取内容
6. **保存文档**：按原始目录结构保存为Markdown文件

### 特点
- 更专注于完整备份
- 保持原始目录结构
- 可能更适合团队知识库备份
- 可能支持更多语雀特有功能

## 主要区别

1. **目标不同**：
   - yuque_hexo：专注于博客发布
   - yuque_backups：专注于文档备份

2. **文件组织方式**：
   - yuque_hexo：按Hexo博客结构组织
   - yuque_backups：按语雀原始目录结构组织

3. **元数据处理**：
   - yuque_hexo：处理并生成Hexo需要的front matter
   - yuque_backups：保持原始Markdown格式

4. **API使用**：
   - 基本API相同，但处理方式不同
   - yuque_hexo可能更关注文章内容和格式
   - yuque_backups更关注完整性和目录结构

5. **增量更新**：
   - yuque_hexo有缓存机制，支持增量更新
   - yuque_backups可能每次都是全量备份

两种方式各有优势，根据你的需求选择合适的工具：如果你主要是为了博客发布，yuque_hexo更合适；如果你需要完整备份知识库，yuque_backups可能更适合。

# 方案一:下载语雀文档到本地
## windwos
```bash
# 1.创建虚拟环境
python -m venv test-env
# 2.进入虚拟环境
.\test-env\Scripts\activate
# 3.更新pip
python.exe -m pip install --upgrade pip
# 4.下载所需模块
pip install requests
pip install aiofiles
pip install aiohttp_requests
# 5.启动脚本(可以现根据所需进行修改)
py.exe .\app.py
```
## mac
```bash
# 1.创建虚拟环境
python -m venv test-env
# 2.进入虚拟环境
source ./test-env/bin/activate
# 3.更新pip
./test-env/bin/python -m pip install --upgrade pip
# 4.下载所需模块
# pip install requests
# pip install aiofiles
# pip install aiohttp_requests
./test-env/bin/python pip install -r requirements.txt
# 5.启动脚本(可以现根据所需进行修改)
./test-env/bin/python app.py 
```
# 方案二:下载语雀文档并转化为hexo格式
```bash
# 下载
./test-env/bin/python  yuque_hexo.py sync
# 清理缓冲(清空已下载的,注意备份)
./test-env/bin/python  yuque_hexo.py clean
```

# 资料
## 没有token的情况下,如何下载语雀文档
语雀公开的文档url后面加/markdown?plain=true&linebreak=false&anchor=false,即可查看markdown格式

## 网络资料
https://app.swaggerhub.com/apis-docs/Jeff-Tian/yuque-open_api/2.0.1#/statistic/statistic_api_v2_statistic_by_docs  
https://blog.weiyan.cc/tech/try-yuque-api/