#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import re
import shutil
import hashlib
import queue
import threading
from datetime import datetime
import requests
from pathlib import Path
from html import unescape
import yaml
import pandas as pd

# 当前工作目录
cwd = os.getcwd()

# 输出日志类
class Out:
    @staticmethod
    def info(*args):
        print("\033[32m[INFO]\033[0m", *args)
    
    @staticmethod
    def warn(*args):
        print("\033[33m[WARNING]\033[0m", *args)
    
    @staticmethod
    def error(*args):
        print("\033[31m[ERROR]\033[0m", *args)

# 输出实例
out = Out()

# 默认配置
images_path = 'source/images'
default_config = {
    'postPath': 'source/_posts/yuque',
    'cachePath': 'yuque.json',
    'lastGeneratePath': '',
    'mdNameFormat': 'title',
    'baseUrl': 'https://www.yuque.com/api/v2/',
    'token': os.environ.get('YUQUE_TOKEN'),
    'login': '',
    'repo': '',
    'adapter': 'hexo',
    'concurrency': 5,
    'onlyPublished': False,
    'onlyPublic': False,
    'imgCdn': {
        'concurrency': 0,
        'enabled': False,
        'imageBed': 'qiniu',
        'host': '',
        'bucket': '',
        'region': '',
        'prefixKey': '',
    },
}

# 加载配置
def load_config():
    config_path = os.path.join(cwd, 'yuque.config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            yuque_config = json.load(f)
            if not isinstance(yuque_config, dict):
                out.error('yuque.config.json should be an object.')
                return None
            config = {**default_config, **yuque_config}
            return config
    except FileNotFoundError:
        out.error('yuque.config.json not found in current directory')
        return None
    except json.JSONDecodeError:
        out.error('yuque.config.json is not a valid JSON file')
        return None
    except Exception as e:
        out.error(f'Failed to load config: {str(e)}')
        return None

# 工具函数
def is_post(post):
    """判断是否为文章"""
    return isinstance(post, dict) and 'body' in post and 'title' in post

def format_date(date_str):
    """格式化日期"""
    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    return dt.strftime('%Y-%m-%d %H:%M:%S %z')

def format_raw(body):
    """格式化markdown内容"""
    multi_br = re.compile(r'(<br>[\s\n]){2}', re.IGNORECASE)
    multi_br_end = re.compile(r'(<br \/>[\n]?){2}', re.IGNORECASE)
    br_bug = re.compile(r'<br \/>', re.IGNORECASE)
    hidden_content = re.compile(r'<div style="display:none">[\s\S]*?<\/div>', re.IGNORECASE)
    empty_anchor = re.compile(r'<a name=\".*?\"><\/a>', re.IGNORECASE)
    
    body = hidden_content.sub('', body)
    body = multi_br.sub('<br>', body)
    body = multi_br_end.sub('<br />\n', body)
    body = br_bug.sub('\n', body)
    body = empty_anchor.sub('', body)
    
    # 这里不实现prettier格式化，直接返回处理后的body
    return body

def format_tags(tags):
    """格式化标签"""
    if not isinstance(tags, list):
        tags = []
    return f"[{','.join(tags)}]"

def format_list(lst):
    """格式化嵌套数组"""
    result = []
    for item in lst or []:
        if isinstance(item, list):
            result.append(format_list(item))
        else:
            result.append(str(item))
    return f"[{','.join(result)}]"

# 添加 TocNode 类
class TocNode:
    def __init__(self, node_type, node_title, node_uuid, parent_uuid, doc_id, repo_id, repo_name):
        self.node_type = node_type
        self.node_title = node_title
        self.node_uuid = node_uuid
        self.parent_uuid = parent_uuid
        self.child_node_list = []
        self.doc_id = doc_id
        self.repo_id = repo_id
        self.repo_name = repo_name

# 添加获取标签的函数
def get_tags(doc_id, toc_data):
    """
    从TOC数据中获取文档的标签数组
    
    Args:
        doc_id: 文档ID
        toc_data: 目录数据，格式为 {node_uuid: TocNode, ...}
        
    Returns:
        list: 标签数组，包含从根目录到文档的所有父级目录名称
    """
    if not toc_data:
        out.warn(f"TOC data is empty, cannot get tags for doc_id: {doc_id}")
        return []
        
    tags = []
    
    # 输出调试信息
    out.info(f"Looking for doc_id: {doc_id} in TOC data with {len(toc_data)} items")
    
    # 查找文档节点
    doc_node = None
    for uuid, node in toc_data.items():
        # 确保 doc_id 是字符串进行比较
        if str(node.doc_id) == str(doc_id):
            doc_node = node
            out.info(f"Found document node: {node.node_title}")
            break
    
    if not doc_node:
        out.warn(f"Document node not found for doc_id: {doc_id}")
        return tags
    
    # 添加知识库名称
    # tags.append(doc_node.repo_name)
    # out.info(f"Added repo name to tags: {doc_node.repo_name}")
    
    # 构建路径
    path = []
    current_node = doc_node
    while current_node.parent_uuid and current_node.parent_uuid != "root":
        parent_node = toc_data.get(current_node.parent_uuid)
        if parent_node and parent_node.node_title != "根目录":
            path.insert(0, parent_node.node_title)
            out.info(f"Added parent node to path: {parent_node.node_title}")
        if not parent_node:
            out.warn(f"Parent node not found for uuid: {current_node.parent_uuid}")
            break
        current_node = parent_node
    
    # 添加路径中的目录作为标签
    tags.extend(path)
    out.info(f"Final tags: {tags}")
    
    return tags

# 语雀客户端
class YuqueClient:
    def __init__(self, config):
        self.config = config.copy()
        self.token = config['token']
        self.user_id = None
        self.repo_id = None
        out.info(f"create client: baseUrl: {config['baseUrl']}, login: {config['login']}, repo: {config['repo']}")

    def _fetch(self, method, api, data=None):
        base_url = self.config['baseUrl'].rstrip('/')
        timeout = self.config.get('timeout', 10000) / 1000
        
        # 构建API路径
        path = f"{base_url}/{api.lstrip('/')}"
        out.info(f"request data: api: {path}, data: {data}")
        
        try:
            headers = {
                'User-Agent': 'yuque-hexo',
                'X-Auth-Token': self.token
            }
            
            if method.upper() == 'GET':
                response = requests.get(path, params=data, timeout=timeout, headers=headers)
            else:
                response = requests.post(path, json=data, timeout=timeout, headers=headers)
            
            if response.status_code != 200:
                out.error(f"API request failed with status {response.status_code}: {response.text}")
                return None
            
            return response.json()
        except Exception as e:
            out.error(f"请求数据失败: {str(e)}")
            return None

    def get_user_id(self):
        """获取用户ID"""
        if self.user_id:
            return self.user_id
            
        user_resp = self._fetch('GET', 'user')
        if user_resp and 'data' in user_resp:
            self.user_id = user_resp['data'].get('id')
            out.info(f"当前用户ID: {self.user_id}")
            return self.user_id
        else:
            out.error("用户ID获取失败，请检查Token")
            return None

    def get_repo_id(self):
        """获取知识库ID"""
        if self.repo_id:
            return self.repo_id
            
        user_id = self.get_user_id()
        if not user_id:
            return None
            
        repos_resp = self._fetch('GET', f'users/{user_id}/repos')
        if repos_resp and 'data' in repos_resp:
            for repo in repos_resp['data']:
                if (repo.get('namespace') == f"{self.config['login']}/{self.config['repo']}" or 
                    (repo.get('name') == self.config['repo'] and 
                     repo.get('user', {}).get('login') == self.config['login'])):
                    self.repo_id = repo.get('id')
                    out.info(f"找到知识库ID: {self.repo_id}")
                    return self.repo_id
            
            out.error(f"未找到知识库: {self.config['login']}/{self.config['repo']}")
            return None
        else:
            out.error("获取知识库列表失败")
            return None

    def get_toc(self):
        """获取知识库目录结构"""
        repo_id = self.get_repo_id()
        if not repo_id:
            return None
            
        return self._fetch('GET', f'repos/{repo_id}/toc')

    def get_doc(self, doc_id):
        """获取文档详情"""
        repo_id = self.get_repo_id()
        if not repo_id:
            return None
            
        return self._fetch('GET', f'repos/{repo_id}/docs/{doc_id}')

# 图片转本地功能
def img2local(post, config):
    # 确保images目录存在
    img_dir = os.path.join(cwd, images_path)
    os.makedirs(img_dir, exist_ok=True)
    out.info(f"Ensuring image directory exists: {img_dir}")

    body = post['body']
    img_pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    
    def process_image(match):
        alt_text = match.group(1)
        img_url = match.group(2)
        
        try:
            # 创建images目录
            img_dir = os.path.join(cwd, images_path)
            os.makedirs(img_dir, exist_ok=True)
            out.info(f"Created image directory: {img_dir}")
            
            # 下载图片
            out.info(f"Downloading image from: {img_url}")
            response = requests.get(img_url, timeout=10)
            if response.status_code == 200:
                # 获取图片格式
                content_type = response.headers.get('content-type', '')
                ext = content_type.split('/')[-1] if content_type else 'png'
                if ext not in ['jpeg', 'jpg', 'png', 'gif', 'webp']:
                    ext = 'png'
                
                # 生成文件名
                date_str = datetime.now().strftime('%Y%m%d')
                counter = 1
                while True:
                    img_name = f"{date_str}_{counter}.{ext}"
                    img_path = os.path.join(img_dir, img_name)
                    if not os.path.exists(img_path):
                        break
                    counter += 1
                
                # 保存图片
                out.info(f"Saving image to: {img_path}")
                with open(img_path, 'wb') as f:
                    f.write(response.content)
                
                # 返回新的图片链接
                out.info(f"Image saved successfully: {img_name}")
                return f"![{alt_text}](./images/{img_name})"
            else:
                out.warn(f"Failed to download image {img_url}, status code: {response.status_code}")
                return match.group(0)
        except requests.RequestException as e:
            out.warn(f"Network error while downloading image {img_url}: {str(e)}")
            return match.group(0)
        except IOError as e:
            out.warn(f"IO error while saving image {img_url}: {str(e)}")
            return match.group(0)
        except Exception as e:
            out.warn(f"Unexpected error processing image {img_url}: {str(e)}")
            return match.group(0)
    
    body = img_pattern.sub(process_image, body)
    post['body'] = body
    return post

# 图片转CDN功能
def img2cdn(post, config):
    """将文章中的图片转为CDN链接或本地存储"""
    # TODO 实现图片转CDN的逻辑
    pass    

# Hexo适配器
def hexo_adapter(post, config):
    """Hexo文章生成适配器"""

    # 处理图片
    if config.get('saveImage', False):
        # 如果开启了本地存储，这里应该调用img2local函数
        if config['localImage']:
            post = img2local(post, config)
        # 如果开启了图片CDN转换，这里应该调用img2cdn函数
        elif config['imgCdn']['enabled']:
            post = img2cdn(post, config)
        
    
    # 解析front matter
    body = unescape(post['body'])
    
    # 处理front matter中的<br/>为\n
    regex = re.compile(r'(title:|layout:|tags:|date:|categories:){1}(\S|\s)+?---', re.IGNORECASE)
    body = regex.sub(lambda a: re.sub(r'(<br \/>|<br>|<br\/>)', '\n', a.group(0)), body)
    
    # 支持提示区块语法
    color_blocks = {
        ':::tips\n': '<div style="background: #FFFBE6;padding:10px;border: 1px solid #C3C3C3;border-radius:5px;margin-bottom:5px;">',
        ':::danger\n': '<div style="background: #FFF3F3;padding:10px;border: 1px solid #DEB8BE;border-radius:5px;margin-bottom:5px;">',
        ':::info\n': '<div style="background: #E8F7FF;padding:10px;border: 1px solid #ABD2DA;border-radius:5px;margin-bottom:5px;">',
        '\\s+:::': '</div>',
    }
    
    for key, value in color_blocks.items():
        body = re.sub(key, value, body, flags=re.IGNORECASE|re.MULTILINE)
    
    # 这里简化front matter解析，实际应该使用更复杂的解析
    front_matter_match = re.match(r'^---\n([\s\S]*?)\n---\n([\s\S]*)$', body)
    
    if front_matter_match:
        front_matter_text = front_matter_match.group(1)
        content = front_matter_match.group(2)
        
        # 解析front matter
        try:
            data = yaml.safe_load(front_matter_text) or {}
        except:
            data = {}
    else:
        data = {}
        content = body
    
    # 格式化正文
    raw = format_raw(content)
    
    # 准备front matter属性
    title = post['title'].replace('"', '')
    urlname = post['slug']
    date = data.get('date') or format_date(post['created_at'])
    
    # 获取tags - 确保使用post中的tags
    tags = post.get('tags', [])
    # 如果post中没有tags，再尝试从data中获取
    if not tags:
        tags = data.get('tags', [])
    
    # 输出调试信息
    out.info(f"Final tags for {title}: {tags}")
    
    categories = data.get('categories') or []
    
    # 创建props对象
    props = {
        'title': title,
        'urlname': urlname,
        'date': date,
    }
    
    # 合并data中的其他属性
    if isinstance(data, dict):
        for key, value in data.items():
            if key not in ['tags', 'title', 'urlname', 'date', 'categories']:
                props[key] = value
    
    # 确保tags和categories不被覆盖
    props['tags'] = tags
    props['categories'] = categories
    
    # 生成front matter
    front_matter = yaml.dump(props, allow_unicode=True)
    
    # 生成最终文本
    text = f"---\n{front_matter}---\n\n{raw}"
    return text

# Markdown适配器
def markdown_adapter(post, config):
    """Markdown文章生成适配器"""

    # 处理图片
    if config.get('saveImage', False):
        # 如果开启了本地存储，这里应该调用img2local函数
        if config['localImage']:
            post = img2local(post, config)
        # 如果开启了图片CDN转换，这里应该调用img2cdn函数
        elif config['imgCdn']['enabled']:
            post = img2cdn(post, config)
    
    body = post['body']
    raw = format_raw(body)
    return raw


# 获取适配器
def get_adapter(adapter_name, config):
    """获取适配器函数"""
    internal_adapters = ['markdown', 'hexo']
    
    if adapter_name in internal_adapters:
        if adapter_name == 'markdown':
            return markdown_adapter
        elif adapter_name == 'hexo':
            return hexo_adapter
    else:
        # 自定义适配器，这里简化处理，实际应该支持自定义适配器
        out.error(f"adapter ({adapter_name}) is invalid.")
        exit(-1)

# 下载器
class Downloader:
    def __init__(self, config):
        self.client = YuqueClient(config)
        self.config = config
        self.cache_path = os.path.join(cwd, config['cachePath'])
        self.post_basic_path = os.path.join(cwd, config['postPath'])
        self._cached_articles = []
        
        # 确保目录存在
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        os.makedirs(self.post_basic_path, exist_ok=True)

    def get_file_name(self, post):
        """
        根据配置获取文件名
        
        Args:
            post: 文章信息字典
            
        Returns:
            str: 文件名（不包含扩展名）
        """
        name_format = self.config.get('mdNameFormat', 'title')
        
        if name_format == 'title':
            # 使用标题作为文件名
            title = post.get('title', '').strip()
            if not title:
                return post.get('slug', 'untitled')
            return title
        elif name_format == 'slug':
            # 使用 slug 作为文件名
            return post.get('slug', 'untitled')
        elif name_format == 'timestamp':
            # 使用时间戳作为文件名
            timestamp = int(time.time())
            return f"{timestamp}_{post.get('slug', 'untitled')}"
        else:
            # 默认使用标题
            return post.get('title', post.get('slug', 'untitled'))

    def traverse_toc(self, toc_data, parent_path=''):
        """递归遍历目录结构，下载文档"""
        if not toc_data or 'data' not in toc_data:
            return
            
        for item in toc_data['data']:
            current_path = os.path.join(parent_path, item.get('title', ''))
            
            if item.get('type') == 'DOC' and item.get('doc_id'):
                # 获取文档详情
                doc_resp = self.client.get_doc(item['doc_id'])
                if doc_resp and 'data' in doc_resp:
                    doc = doc_resp['data']
                    
                    # 准备文档数据
                    article = {
                        'title': doc.get('title', ''),
                        'slug': doc.get('slug', ''),
                        'created_at': doc.get('created_at', ''),
                        'updated_at': doc.get('updated_at', ''),
                        'published_at': doc.get('published_at', ''),
                        'body': doc.get('body', ''),
                        'path': current_path,  # 保存文档路径
                        'tags': current_path.split(os.sep)[:-1]  # 使用路径作为标签
                    }
                    
                    # 保存到缓存
                    self._cached_articles.append(article)
                    
                    # 生成文档
                    self.generate_post(article)
            
            # 递归处理子目录
            if item.get('children'):
                self.traverse_toc({'data': item['children']}, current_path)

    def update_tags_from_toc(self, toc_data):
        """从TOC更新文档的标签"""
        if not toc_data or 'data' not in toc_data:
            return
        
        # 创建文档标题到路径的映射
        doc_paths = {}
        
        def traverse_toc(items):
            for item in items:
                if item.get('type') == 'DOC':
                    # 获取完整路径
                    path = []
                    current = item
                    while current.get('parent_uuid'):
                        for node in toc_data['data']:
                            if node['uuid'] == current['parent_uuid']:
                                path.insert(0, node['title'])
                                current = node
                                break
                    
                    # 保存文档标题和路径的映射
                    doc_paths[item['title']] = path  # 不包含文档本身的标题
        
        # 遍历TOC构建路径映射
        traverse_toc(toc_data['data'])
        
        # 更新已下载文档的标签
        updated_count = 0
        for root, _, files in os.walk(self.post_basic_path):
            for file in files:
                if not file.endswith('.md'):
                    continue
                    
                file_path = os.path.join(root, file)
                try:
                    # 读取markdown文件
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 解析front matter
                    if content.startswith('---'):
                        _, front_matter, body = content.split('---', 2)
                        meta = yaml.safe_load(front_matter)
                        
                        # 获取文档标题
                        title = meta.get('title', '')
                        if title in doc_paths:
                            # 更新标签和分类
                            tags = doc_paths[title]
                            
                            # 直接设置标签和分类，不使用YAML引用
                            meta['tags'] = tags
                            meta['categories'] = tags
                            
                            # 使用自定义的YAML dumper
                            class NoAliasDumper(yaml.SafeDumper):
                                def ignore_aliases(self, data):
                                    return True
                            
                            # 重新生成文档
                            new_content = f"---\n{yaml.dump(meta, allow_unicode=True, Dumper=NoAliasDumper)}---{body}"
                            
                            # 写回文件
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(new_content)
                                
                            updated_count += 1
                            out.info(f"Updated tags for: {title}")
                            out.info(f"New tags: {tags}")
                
                except Exception as e:
                    out.error(f"Failed to update tags for {file}: {str(e)}")
        
        out.info(f"Updated tags for {updated_count} documents")

    def auto_update(self):
        """执行完整的更新流程"""
        try:
            # 获取目录结构
            toc_data = self.client.get_toc()
            if not toc_data:
                out.error("Failed to get TOC data")
                return
                
            # 清空缓存
            self._cached_articles = []
            
            # 遍历目录结构，下载文档
            self.traverse_toc(toc_data)
            
            # 从TOC更新标签
            self.update_tags_from_toc(toc_data)
            
            # 导出TOC到Excel
            self.export_toc_to_excel(toc_data)
            
            out.info('download articles done!')
        except Exception as e:
            out.error(f"Auto update failed: {str(e)}")
            raise

    def generate_post(self, post):
        """生成单篇文章"""
        file_name = self.get_file_name(post)
        post_path = os.path.join(self.post_basic_path, f"{file_name}.md")
        
        # 获取适配器
        adapter_name = self.config['adapter']
        transform = get_adapter(adapter_name, self.config)
        
        out.info(f"generate post file: {post_path}")
        text = transform(post, self.config)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(post_path), exist_ok=True)
        
        # 写入文件
        with open(post_path, 'w', encoding='utf-8') as f:
            f.write(text)

    def export_toc_to_excel(self, toc_data, output_path=None):
        """导出TOC到Excel文件"""
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f'yuque_toc_{timestamp}.xlsx'
        
        # 准备数据
        rows = []
        
        def traverse_toc(items, level=0):
            for item in items:
                # 获取完整路径
                path = []
                current = item
                while current.get('parent_uuid'):
                    for node in toc_data['data']:
                        if node['uuid'] == current['parent_uuid']:
                            path.insert(0, node['title'])
                            current = node
                            break
                path.append(item['title'])
                
                rows.append({
                    '层级': level,
                    '类型': item.get('type', ''),
                    '标题': item.get('title', ''),
                    '文档ID': item.get('doc_id', ''),
                    '路径': '/'.join(path) if path else item.get('title', '')
                })
                
                # 递归处理子目录
                if item.get('children'):
                    traverse_toc(item['children'], level + 1)
        
        # 遍历TOC构建数据
        traverse_toc(toc_data['data'])
        
        # 创建DataFrame
        df = pd.DataFrame(rows)
        
        # 调整列顺序和名称
        df = df[['层级', '类型', '标题', '文档ID', '路径']]
        
        # 写入Excel
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='目录结构')
            
            # 设置列宽
            worksheet = writer.sheets['目录结构']
            worksheet.column_dimensions['A'].width = 10  # 层级
            worksheet.column_dimensions['B'].width = 15  # 类型
            worksheet.column_dimensions['C'].width = 40  # 标题
            worksheet.column_dimensions['D'].width = 15  # 文档ID
            worksheet.column_dimensions['E'].width = 50  # 路径
        
        out.info(f"TOC exported to: {output_path}")

# 清理工具
class Cleaner:
    @staticmethod
    def clean_posts(config):
        """清理生成的文章目录"""
        post_path = config['postPath']
        dist = os.path.join(cwd, post_path)
        out.info(f"remove yuque posts: {dist}")
        shutil.rmtree(dist, ignore_errors=True)
    
    @staticmethod
    def clean_images():
        """清理生成的文章目录"""
        dist = os.path.join(cwd, images_path)
        out.info(f"remove yuque images: {dist}")
        shutil.rmtree(dist, ignore_errors=True)
    @staticmethod
    def clear_cache():
        """清理文章缓存"""
        cache_path = os.path.join(cwd, 'yuque.json')
        try:
            out.info(f"remove yuque.json: {cache_path}")
            os.unlink(cache_path)
        except Exception as e:
            out.warn(f"remove empty yuque.json: {str(e)}")
    
    @staticmethod
    def clear_last_generate(config):
        """清理上次生成的时间戳文件"""
        last_generate_path = config.get('lastGeneratePath')
        if not last_generate_path:
            return
        
        dist = os.path.join(cwd, last_generate_path)
        out.info(f"remove last generated timestamp: {dist}")
        try:
            os.unlink(dist)
        except:
            pass

# 命令行接口
def sync_command():
    """同步命令"""
    config = load_config()
    if not config:
        exit(0)
    
    # 如果没有设置lastGeneratePath，清理之前的目录
    if config['lastGeneratePath'] == '':
        out.info('clear previous directory.')
        Cleaner.clean_posts(config)
    
    # 从语雀获取文章或缓存
    downloader = Downloader(config)
    downloader.auto_update()
    out.info('yuque-hexo sync done!')

def clean_command():
    """清理命令"""
    config = load_config()
    if not config:
        exit(0)
    
    Cleaner.clean_posts(config)
    Cleaner.clean_images()
    Cleaner.clear_cache()
    Cleaner.clear_last_generate(config)
    out.info('yuque-hexo clean done!')

def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='yuque-hexo: A downloader for articles from yuque')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # sync命令
    sync_parser = subparsers.add_parser('sync', help='Sync articles from yuque')
    
    # clean命令
    clean_parser = subparsers.add_parser('clean', help='Clean generated files')
    
    args = parser.parse_args()
    
    if args.command == 'sync':
        sync_command()
    elif args.command == 'clean':
        clean_command()
    else:
        parser.print_help()

if __name__ == '__main__':
    main()