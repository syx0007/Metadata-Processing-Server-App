import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from mutagen import File
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, USLT, APIC, TDRC, delete, COMM
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from urllib.parse import urlparse
import tempfile
import threading
import time
import logging
import mimetypes
import traceback
import shutil
import signal
import atexit

# 全局变量
app = Flask(__name__)
CORS(app)
TEMP_DIR = tempfile.gettempdir()
FILE_CLEANUP_TIME = 300  # 5分钟
file_registry = {}
is_shutting_down = False
logger = logging.getLogger(__name__)

def download_file(url, file_path):
    """下载文件到指定路径"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive'
        }
        
        logger.info(f"开始下载: {url}")
        response = requests.get(url, stream=True, headers=headers, timeout=60)
        response.raise_for_status()
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        logger.info(f"下载完成: {file_path}, 文件大小: {os.path.getsize(file_path)} bytes")
        return True
        
    except Exception as e:
        logger.error(f"下载失败: {e}")
        return False

def download_cover(cover_url):
    """下载封面图片"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        logger.info(f"开始下载封面: {cover_url}")
        response = requests.get(cover_url, headers=headers, timeout=30)
        response.raise_for_status()
        logger.info("封面下载成功")
        return response.content
    except Exception as e:
        logger.error(f"封面下载失败: {e}")
        return None

def strip_existing_metadata(file_path):
    """删除文件中的所有现有元数据"""
    try:
        logger.info(f"开始清理现有元数据: {file_path}")
        
        # 检测文件类型
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.mp3':
            # 对于MP3，使用mutagen的delete函数彻底删除ID3标签
            try:
                delete(file_path)
                logger.info("MP3 ID3标签删除成功")
            except Exception as e:
                logger.warning(f"删除MP3标签时出错: {e}")
                # 尝试直接操作文件
                try:
                    audio = MP3(file_path)
                    if audio.tags:
                        audio.delete()
                        audio.save()
                except:
                    pass
            
        elif file_ext == '.flac':
            # 对于FLAC，清除所有标签
            try:
                audio = FLAC(file_path)
                audio.clear()
                audio.save()
                logger.info("FLAC标签清除成功")
            except Exception as e:
                logger.warning(f"清除FLAC标签时出错: {e}")
            
        elif file_ext in ['.ogg', '.oga']:
            # 对于OGG，清除所有标签
            try:
                audio = OggVorbis(file_path)
                audio.delete()
                audio.save()
                logger.info("OGG标签清除成功")
            except Exception as e:
                logger.warning(f"清除OGG标签时出错: {e}")
            
        elif file_ext in ['.m4a', '.mp4']:
            # 对于MP4，清除所有标签
            try:
                audio = MP4(file_path)
                audio.delete()
                audio.save()
                logger.info("MP4标签清除成功")
            except Exception as e:
                logger.warning(f"清除MP4标签时出错: {e}")
            
        elif file_ext == '.wav':
            # 对于WAV，尝试清除ID3标签
            try:
                audio = WAVE(file_path)
                if hasattr(audio, 'tags') and audio.tags:
                    audio.delete()
                    audio.save()
                logger.info("WAV标签清除成功")
            except Exception as e:
                logger.warning(f"清除WAV标签时出错: {e}")
                
        elif file_ext == '.aiff':
            # 对于AIFF，尝试清除ID3标签
            try:
                audio = AIFF(file_path)
                if hasattr(audio, 'tags') and audio.tags:
                    audio.delete()
                    audio.save()
                logger.info("AIFF标签清除成功")
            except Exception as e:
                logger.warning(f"清除AIFF标签时出错: {e}")
        
        logger.info("现有元数据清理完成")
        return True
        
    except Exception as e:
        logger.error(f"清理元数据失败: {e}")
        logger.error(traceback.format_exc())
        return False

def add_metadata_to_mp3(file_path, metadata):
    """向MP3文件添加元数据"""
    try:
        logger.info(f"开始处理MP3文件: {file_path}")
        
        # 确保彻底删除现有标签
        try:
            delete(file_path)
        except:
            pass
        
        # 重新加载文件
        audio = MP3(file_path)
        
        # 检查是否还有标签，如果有则删除
        if audio.tags:
            audio.delete()
            audio.save()
        
        # 重新加载确保没有标签
        audio = MP3(file_path)
        
        # 添加新标签
        audio.add_tags()
        tags = audio.tags
        
        # 设置基本元数据
        if metadata.get('title'):
            tags.add(TIT2(encoding=3, text=metadata['title']))
        if metadata.get('artist'):
            tags.add(TPE1(encoding=3, text=metadata['artist']))
        if metadata.get('album'):
            tags.add(TALB(encoding=3, text=metadata['album']))
        if metadata.get('year'):
            # 确保年份是ASCII字符串
            year_str = str(metadata['year'])
            if year_str:
                tags.add(TDRC(encoding=3, text=year_str))
        
        # 添加歌词
        if metadata.get('lyrics'):
            tags.add(USLT(encoding=3, lang='eng', desc='', text=metadata['lyrics']))
        
        # 添加注释
        if metadata.get('tips'):
            tags.add(COMM(encoding=3, lang='eng', desc='', text=metadata['tips']))
        
        # 添加封面
        if metadata.get('cover_data'):
            cover_data = metadata['cover_data']
            tags.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=cover_data
            ))
        
        audio.save(v2_version=3)  # 使用ID3v2.3版本
        logger.info("MP3元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加MP3元数据失败: {e}")
        logger.error(traceback.format_exc())
        return False

def add_metadata_to_flac(file_path, metadata):
    """向FLAC文件添加元数据"""
    try:
        logger.info(f"开始处理FLAC文件: {file_path}")
        audio = FLAC(file_path)
        
        # 清除现有标签
        audio.clear()
        
        # 设置基本元数据
        if metadata.get('title'):
            audio['title'] = [metadata['title']]
        if metadata.get('artist'):
            audio['artist'] = [metadata['artist']]
        if metadata.get('album'):
            audio['album'] = [metadata['album']]
        if metadata.get('year'):
            audio['date'] = [str(metadata['year'])]
        
        # 添加歌词
        if metadata.get('lyrics'):
            audio['lyrics'] = [metadata['lyrics']]
        
        # 添加注释
        if metadata.get('tips'):
            audio['comment'] = [metadata['tips']]
        
        # 添加封面
        if metadata.get('cover_data'):
            cover_data = metadata['cover_data']
            picture = FLAC.Picture()
            picture.type = 3
            picture.mime = 'image/jpeg'
            picture.desc = 'Cover'
            picture.data = cover_data
            audio.clear_pictures()
            audio.add_picture(picture)
        
        audio.save()
        logger.info("FLAC元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加FLAC元数据失败: {e}")
        logger.error(traceback.format_exc())
        return False

def add_metadata_to_ogg(file_path, metadata):
    """向OGG文件添加元数据"""
    try:
        logger.info(f"开始处理OGG文件: {file_path}")
        audio = OggVorbis(file_path)
        
        # 清除现有标签
        audio.delete()
        
        # 设置基本元数据
        if metadata.get('title'):
            audio['title'] = metadata['title']
        if metadata.get('artist'):
            audio['artist'] = metadata['artist']
        if metadata.get('album'):
            audio['album'] = metadata['album']
        if metadata.get('year'):
            audio['date'] = str(metadata['year'])
        if metadata.get('lyrics'):
            audio['lyrics'] = metadata['lyrics']
        if metadata.get('tips'):
            audio['comment'] = metadata['tips']
        
        audio.save()
        logger.info("OGG元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加OGG元数据失败: {e}")
        return False

def add_metadata_to_mp4(file_path, metadata):
    """向MP4文件添加元数据"""
    try:
        logger.info(f"开始处理MP4文件: {file_path}")
        audio = MP4(file_path)
        
        # 清除现有标签
        audio.delete()
        
        # MP4标签映射
        tag_map = {
            'title': '\xa9nam',
            'artist': '\xa9ART',
            'album': '\xa9alb',
            'year': '\xa9day',
            'lyrics': '\xa9lyr',
            'tips': '\xa9cmt'
        }
        
        # 设置基本元数据
        if metadata.get('title'):
            audio[tag_map['title']] = [metadata['title']]
        if metadata.get('artist'):
            audio[tag_map['artist']] = [metadata['artist']]
        if metadata.get('album'):
            audio[tag_map['album']] = [metadata['album']]
        if metadata.get('year'):
            audio[tag_map['year']] = [str(metadata['year'])]
        if metadata.get('lyrics'):
            audio[tag_map['lyrics']] = [metadata['lyrics']]
        if metadata.get('tips'):
            audio[tag_map['tips']] = [metadata['tips']]
        
        # 添加封面
        if metadata.get('cover_data'):
            cover_data = metadata['cover_data']
            audio['covr'] = [MP4.Cover(cover_data)]
        
        audio.save()
        logger.info("MP4元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加MP4元数据失败: {e}")
        return False

def add_metadata_to_wav(file_path, metadata):
    """向WAV文件添加元数据"""
    try:
        logger.info(f"开始处理WAV文件: {file_path}")
        audio = WAVE(file_path)
        
        # WAV文件通常使用ID3标签
        if not audio.tags:
            audio.add_tags()
        
        # 设置基本元数据
        if metadata.get('title'):
            audio.tags['TIT2'] = TIT2(encoding=3, text=metadata['title'])
        if metadata.get('artist'):
            audio.tags['TPE1'] = TPE1(encoding=3, text=metadata['artist'])
        if metadata.get('album'):
            audio.tags['TALB'] = TALB(encoding=3, text=metadata['album'])
        if metadata.get('year'):
            audio.tags['TDRC'] = TDRC(encoding=3, text=str(metadata['year']))
        if metadata.get('lyrics'):
            audio.tags['USLT'] = USLT(encoding=3, lang='eng', desc='', text=metadata['lyrics'])
        if metadata.get('tips'):
            audio.tags['COMM'] = COMM(encoding=3, lang='eng', desc='', text=metadata['tips'])
        
        audio.save()
        logger.info("WAV元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加WAV元数据失败: {e}")
        return False

def add_metadata_to_aiff(file_path, metadata):
    """向AIFF文件添加元数据"""
    try:
        logger.info(f"开始处理AIFF文件: {file_path}")
        audio = AIFF(file_path)
        
        # AIFF文件通常使用ID3标签
        if not audio.tags:
            audio.add_tags()
        
        # 设置基本元数据
        if metadata.get('title'):
            audio.tags['TIT2'] = TIT2(encoding=3, text=metadata['title'])
        if metadata.get('artist'):
            audio.tags['TPE1'] = TPE1(encoding=3, text=metadata['artist'])
        if metadata.get('album'):
            audio.tags['TALB'] = TALB(encoding=3, text=metadata['album'])
        if metadata.get('year'):
            audio.tags['TDRC'] = TDRC(encoding=3, text=str(metadata['year']))
        if metadata.get('lyrics'):
            audio.tags['USLT'] = USLT(encoding=3, lang='eng', desc='', text=metadata['lyrics'])
        if metadata.get('tips'):
            audio.tags['COMM'] = COMM(encoding=3, lang='eng', desc='', text=metadata['tips'])
        
        audio.save()
        logger.info("AIFF元数据添加成功")
        return True
        
    except Exception as e:
        logger.error(f"添加AIFF元数据失败: {e}")
        return False

def add_metadata_to_file(file_path, metadata):
    """根据文件类型添加元数据"""
    try:
        # 首先清理现有元数据
        strip_existing_metadata(file_path)
        
        # 检测文件类型
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.mp3':
            return add_metadata_to_mp3(file_path, metadata)
        elif file_ext == '.flac':
            return add_metadata_to_flac(file_path, metadata)
        elif file_ext in ['.ogg', '.oga']:
            return add_metadata_to_ogg(file_path, metadata)
        elif file_ext in ['.m4a', '.mp4']:
            return add_metadata_to_mp4(file_path, metadata)
        elif file_ext == '.wav':
            return add_metadata_to_wav(file_path, metadata)
        elif file_ext == '.aiff':
            return add_metadata_to_aiff(file_path, metadata)
        else:
            logger.error(f"不支持的文件格式: {file_ext}")
            return False
            
    except Exception as e:
        logger.error(f"处理文件时出错: {e}")
        logger.error(traceback.format_exc())
        return False

def cleanup_old_files():
    """清理旧文件"""
    while True:
        time.sleep(60)
        if is_shutting_down:
            break
            
        current_time = time.time()
        files_to_delete = []
        
        for file_id, file_info in list(file_registry.items()):
            if current_time - file_info['created_time'] > FILE_CLEANUP_TIME:
                files_to_delete.append((file_id, file_info['path']))
        
        for file_id, file_path in files_to_delete:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                del file_registry[file_id]
                logger.info(f"已清理文件: {file_path}")
            except Exception as e:
                logger.error(f"清理文件失败: {e}")

@app.route('/process-music', methods=['POST', 'OPTIONS'])
def process_music():
    """处理音乐文件"""
    if is_shutting_down:
        return jsonify({'error': '服务器正在关闭'}), 503
        
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
    
    try:
        data = request.get_json()
        logger.info(f"收到请求")
        
        if not data:
            return jsonify({'error': '无效的JSON数据'}), 400
        
        # 验证必需参数
        required_fields = ['url', 'title']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'缺少必需字段: {field}'}), 400
        
        # 生成唯一文件ID
        file_id = str(uuid.uuid4())
        url_path = urlparse(data['url']).path
        original_filename = os.path.basename(url_path) or "audio.mp3"
        
        # 文件路径
        temp_file_path = os.path.join(TEMP_DIR, f"{file_id}_{original_filename}")
        processed_file_path = os.path.join(TEMP_DIR, f"processed_{file_id}_{original_filename}")
        
        # 下载原始文件
        if not download_file(data['url'], temp_file_path):
            return jsonify({'error': '音乐文件下载失败'}), 500
        
        # 检查文件是否存在且大小合理
        if not os.path.exists(temp_file_path) or os.path.getsize(temp_file_path) == 0:
            return jsonify({'error': '下载的文件无效'}), 500
        
        # 下载封面
        cover_data = None
        if data.get('cover_url'):
            cover_data = download_cover(data['cover_url'])
        
        # 准备元数据
        metadata = {
            'title': data['title'],
            'artist': data.get('artist', ''),
            'album': data.get('album', ''),
            'year': data.get('year', ''),
            'lyrics': data.get('lyrics', ''),
            'tips': data.get('tips', ''),
            'cover_data': cover_data
        }
        
        # 复制文件到新路径
        shutil.copy2(temp_file_path, processed_file_path)
        
        # 清理原始文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        
        # 添加元数据
        logger.info("开始添加元数据")
        if not add_metadata_to_file(processed_file_path, metadata):
            if os.path.exists(processed_file_path):
                os.remove(processed_file_path)
            return jsonify({'error': '添加元数据失败，可能是不支持的文件格式'}), 500
        
        # 注册文件
        file_registry[file_id] = {
            'path': processed_file_path,
            'filename': original_filename,
            'created_time': time.time()
        }
        
        download_url = f"http://{request.host}/download/{file_id}"
        return jsonify({
            'success': True,
            'download_url': download_url,
            'file_id': file_id,
            'message': '文件处理成功'
        })
    
    except Exception as e:
        logger.error(f"处理请求时发生错误: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/download/<file_id>')
def download_file_endpoint(file_id):
    """下载文件"""
    if is_shutting_down:
        return jsonify({'error': '服务器正在关闭'}), 503
        
    if file_id not in file_registry:
        return jsonify({'error': '文件不存在或已过期'}), 404
    
    file_info = file_registry[file_id]
    if not os.path.exists(file_info['path']):
        return jsonify({'error': '文件不存在'}), 404
    
    return send_file(
        file_info['path'],
        as_attachment=True,
        download_name=f"processed_{file_info['filename']}"
    )

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """关闭服务器"""
    global is_shutting_down
    is_shutting_down = True
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return jsonify({'status': 'shutting_down', 'message': '服务器正在关闭'})

@app.route('/status')
def status():
    """返回服务器状态"""
    if is_shutting_down:
        return jsonify({'status': 'shutting_down'}), 503
    return jsonify({'status': 'success', 'message': '服务器运行正常'})

@app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'endpoints': {
            'process_music': 'POST /process-music',
            'download': 'GET /download/<file_id>',
            'status': 'GET /status',
            'shutdown': 'POST /shutdown'
        }
    })

def init_app(cache_dir=None):
    """初始化应用程序"""
    global TEMP_DIR, logger
    
    # 设置缓存目录
    if cache_dir and os.path.exists(cache_dir):
        TEMP_DIR = cache_dir
        logger.info(f"使用自定义缓存目录: {TEMP_DIR}")
    else:
        TEMP_DIR = tempfile.gettempdir()
        logger.info(f"使用系统临时目录: {TEMP_DIR}")
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(TEMP_DIR, 'music_metadata_processor.log'))
        ]
    )
    logger = logging.getLogger(__name__)
    
    # 启动清理线程
    cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
    cleanup_thread.start()
    
    logger.info("应用程序初始化完成")
    return app

def run_server(host='127.0.0.1', port=5000, cache_dir=None):
    """运行服务器"""
    init_app(cache_dir)
    logger.info(f"服务器启动: http://{host}:{port}")
    logger.info(f"临时目录: {TEMP_DIR}")
    app.run(host=host, port=port, debug=False)

if __name__ == '__main__':
    run_server()