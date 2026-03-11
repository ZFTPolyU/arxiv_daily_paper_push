import arxiv
import requests
import json
from datetime import datetime
import os
import time

# --- 配置区 (通过环境变量读取) ---
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "your_api_key")  
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

PWC_BASE_URL = "https://arxiv.paperswithcode.com/api/v0/papers/"

def get_code_link(arxiv_url):
    """从 PapersWithCode 获取代码链接"""
    arxiv_id = arxiv_url.split('/')[-1].split('v')[0]
    try:
        r = requests.get(f"{PWC_BASE_URL}{arxiv_id}", timeout=10).json()
        if "official" in r and r["official"]:
            return r["official"]["url"]
    except:
        pass
    return None

def summarize_with_deepseek(paper):
    """使用 DeepSeek 进行论文摘要深度总结 (针对机器人与规划控制领域优化)"""
    prompt_text = f"""你是一个深耕机器人学、四旋翼 (quadrotor) 与强化学习领域的学术分析专家。请根据以下论文的标题和摘要提供结构化的中文深度分析。
    论文标题: {paper['title']}
    论文摘要: {paper['summary']}
    
    请严格按此格式输出：
    【快速抓要点】: （一句话简练说明该研究解决了什么痛点？提出了什么新的网络架构、规划器 (Planner) 或控制算法？得出了什么结论？）
    【逻辑推导】: （还原作者的思考路径。**背景**：现有的规划或控制方法在动态环境/复杂地形下为何失效？**破局**：作者的核心直觉是什么？**拆解**：这个方法具体分几步实现？）
    【技术细节与设定】: （提取摘要中最关键的技术实现细节。例如：强化学习的状态(State)/动作(Action)空间设计、Reward 函数的创新、网络结构的改进 (如加入GRU等)，或是特定的避障/安全约束。）
    【实验环境验证】: （指出该方法是在什么环境中验证的？纯仿真环境 (如 Isaac Sim, PyBullet, Flightmare 等) 还是进行了真实物理世界 (Real-world) 的飞行/行驶测试？是否有提及 Sim-to-Real 的表现？）
    【局限性与突破口】: （基于摘要推断该方法的潜在不足，或未来可以继续挖掘的研究方向。）
    """

    payload = {
        "model": "deepseek-chat", 
        "messages": [
            {"role": "system", "content": "你是一个机器人领域的资深研究员，擅长将复杂的基于学习的规划 (Learning-based Planning)、强化学习和机器人控制算法总结得清晰透彻。"},
            {"role": "user", "content": prompt_text}
        ],
        "stream": False
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        res_json = response.json()
        
        if 'error' in res_json:
            return f"DeepSeek API 报错: {res_json['error']['message']}"
        
        if 'choices' not in res_json:
            return f"API 未预期响应: {json.dumps(res_json)}"

        return res_json['choices'][0]['message']['content']
    except Exception as e:
        return f"网络或系统错误: {str(e)}"

def push_to_telegram(text, parse_mode="Markdown"):
    """发送消息到 Telegram，自带 Markdown 解析失败降级机制"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 Telegram Token 或 Chat ID，跳过推送。")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True # 关闭链接预览
    }
    
    if parse_mode:
        payload["parse_mode"] = parse_mode
        
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        # 如果请求失败
        if response.status_code != 200:
            error_desc = response.json().get("description", "")
            
            # 核心拦截逻辑：捕捉 Markdown 闭合错误
            if "can't parse entities" in error_desc and parse_mode == "Markdown":
                print("⚠️ Telegram Markdown 解析失败，正在自动降级为纯文本重发...")
                # 递归调用自身，将 parse_mode 设为 None
                push_to_telegram(text, parse_mode=None)
            else:
                print(f"❌ Telegram 推送失败: {error_desc}")
                
    except Exception as e:
        print(f"Telegram 推送请求错误: {str(e)}")


if __name__ == "__main__":
    print("正在搜集最新论文...")
    client = arxiv.Client()
    search = arxiv.Search(
        query="(abs:\"air-ground\" OR abs:bimodal OR abs:quadrotor) AND (abs:planning OR abs:navigation OR abs:\"reinforcement learning\" OR abs:RL OR abs:safety)", 
        max_results=10, 
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    
    results = list(client.results(search))
    
    if not results:
        msg = "今日暂无匹配的新论文。"
        print(msg)
        push_to_telegram(msg)
    else:
        # 1. 先发送一条打招呼的头部消息
        header = f"🚀 *ArXiv 每日论文精选 {datetime.now().strftime('%m-%d')}*\n_今日共抓取 {len(results)} 篇最新研究_"
        push_to_telegram(header)
        time.sleep(1) # 暂停 1 秒，防止触发 Telegram 发送频率限制

        # 2. 遍历每一篇论文，单独分析并单独发送
        for i, res in enumerate(results):
            print(f"正在分析并推送第 {i+1}/{len(results)} 篇: {res.title}")
            
            code_url = get_code_link(res.entry_id)
            code_md = f" | [💻 代码]({code_url})" if code_url else ""
            
            paper_info = {
                "title": res.title,
                "summary": res.summary.replace('\n', ' '),
                "url": res.entry_id
            }
            
            summary = summarize_with_deepseek(paper_info)
            
            # 组装单篇论文的消息内容
            paper_msg = f"*{i+1}. {res.title}*\n🔗 [原文]({res.entry_id}){code_md}\n\n{summary}"
            push_to_telegram(paper_msg)
            
            time.sleep(2) # 每发完一篇暂停 2 秒，给 API 留出缓冲时间
        
        # 3. 发送收尾消息
        push_to_telegram("_基于 DeepSeek-V3 自动生成_")
        print("所有论文执行与推送完毕！")
