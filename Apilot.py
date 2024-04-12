import plugins
import requests
import re
import json
import time
from urllib.parse import urlparse
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel import channel
from common.log import logger
from plugins import *
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
BASE_URL_VVHAN = "https://api.vvhan.com/api/"
BASE_URL_ALAPI = "https://v2.alapi.cn/api/"


@plugins.register(
    name="Apilot",
    desire_priority=88,
    hidden=False,
    desc="A plugin to handle specific keywords",
    version="0.2",
    author="vision",
)
class Apilot(Plugin):
    def __init__(self):
        super().__init__()
        try:
            self.conf = super().load_config()
            self.condition_2_and_3_cities = None  # 天气查询，存储重复城市信息，Initially set to None
            if not self.conf:
                logger.warn("[Apilot] inited but alapi_token not found in config")
                self.alapi_token = None # Setting a default value for alapi_token
                self.morning_news_text_enabled = False
            else:
                logger.info("[Apilot] inited and alapi_token loaded successfully")
                self.alapi_token = self.conf["alapi_token"]
                try:
                    self.morning_news_text_enabled = self.conf["morning_news_text_enabled"]
                except:
                    self.morning_news_text_enabled = False
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        except Exception as e:
            raise self.handle_error(e, "[Apiot] init failed, ignore ")

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type not in [
            ContextType.TEXT
        ]:
            return
        content = e_context["context"].content.strip()
        logger.debug("[Apilot] on_handle_context. content: %s" % content)

        if content == "早报":
            news = self.get_morning_news(self.alapi_token, self.morning_news_text_enabled)
            reply_type = ReplyType.IMAGE_URL if self.is_valid_url(news) else ReplyType.TEXT
            reply = self.create_reply(reply_type, news)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return
        if content == "摸鱼":
            moyu = self.get_moyu_calendar()
            reply_type = ReplyType.IMAGE_URL if self.is_valid_url(moyu) else ReplyType.TEXT
            reply = self.create_reply(reply_type, moyu)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content == "摸鱼视频":
            moyu = self.get_moyu_calendar_video()
            reply_type = ReplyType.VIDEO_URL if self.is_valid_url(moyu) else ReplyType.TEXT
            reply = self.create_reply(reply_type, moyu)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content == "八卦":
            bagua = self.get_mx_bagua()
            reply_type = ReplyType.IMAGE_URL if self.is_valid_url(bagua) else ReplyType.TEXT
            reply = self.create_reply(reply_type, bagua)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content == "今日热点":
            content = self.get_hot_trends_A()
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return
        
        if content.startswith("搜人"):
            starname = content[2:].strip()
            content = self.get_starinfo(starname)
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content.startswith("搜图"):
            starname = content[2:].strip()
            content = self.get_starpic(starname)
            reply = self.create_reply(ReplyType.IMAGE_URL, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content.startswith("快递"):
            # Extract the part after "快递"
            tracking_number = content[2:].strip()

            tracking_number = tracking_number.replace('：', ':')  # 替换可能出现的中文符号
            # Check if alapi_token is available before calling the function
            if not self.alapi_token:
                self.handle_error("alapi_token not configured", "快递请求失败")
                reply = self.create_reply(ReplyType.TEXT, "请先配置alapi的token")
            else:
                # Check if the tracking_number starts with "SF" for Shunfeng (顺丰) Express
                if tracking_number.startswith("SF"):
                    # Check if the user has included the last four digits of the phone number
                    if ':' not in tracking_number:
                        reply = self.create_reply(ReplyType.TEXT, "顺丰快递需要补充寄/收件人手机号后四位，格式：SF12345:0000")
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
                        return  # End the function here

                # Call query_express_info function with the extracted tracking_number and the alapi_token from config
                content = self.query_express_info(self.alapi_token, tracking_number)
                reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        horoscope_match = re.match(r'^([\u4e00-\u9fa5]{2}座)$', content)
        if horoscope_match:
            if content in ZODIAC_MAPPING:
                zodiac_english = ZODIAC_MAPPING[content]
                content = self.get_horoscope(self.alapi_token, zodiac_english)
                reply = self.create_reply(ReplyType.TEXT, content)
            else:
                reply = self.create_reply(ReplyType.TEXT, "请重新输入星座名称")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        rate_match = re.search(r'(.{2})(.{2})汇率(\d{8})?$', content)
        if rate_match:
            bank_name = rate_match.group(1).strip()  # 提取银行名称并去掉可能的空格
            currency_name = rate_match.group(2).strip()  # 提取货币名称并去掉可能的空格
            date = rate_match.group(3)  # 提取日期
            content = self.get_exchange_rate(bank_name, currency_name, date)
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        if content.startswith("每日查询"):
            start_index = content.find("每日查询")
            lines = content[start_index + len("每日查询"):].strip().split('\n')
            input_values = [val for val in lines if val.strip()]  # 确保没有空行
            content = self.get_daily_rate(input_values)
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        hot_trend_match = re.search(r'(.{1,6})热榜$', content)
        if hot_trend_match:
            hot_trends_type = hot_trend_match.group(1).strip()  # 提取匹配的组并去掉可能的空格
            content = self.get_hot_trends(hot_trends_type)
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        hot_trend_match_d = re.search(r'(.{1,6})热点$', content)
        if hot_trend_match_d:
            hot_trends_type_d = hot_trend_match_d.group(1).strip()  # 提取匹配的组并去掉可能的空格
            content = self.get_hot_trends_d(hot_trends_type_d)
            reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

        #if content.startswith("视频"):
        video_trigger = ["视频字幕", "视频总结", "视频数据"]
        for trigger in video_trigger:
            if trigger in content:
                video_url_match = re.search(f'{trigger}(.*?)$', content)
                if video_url_match:
                    video_url = self.extract_video_url(video_url_match.group(1))
                    if video_url:
                        content = self.get_video_summary(video_url, trigger)
                        reply = self.create_reply(ReplyType.TEXT, content)
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
                        return

        video_download = ["视频下载", "视频解析", "复制打开抖音"]
        for trigger in video_download:
            if trigger in content:
                video_url_match = re.search(f'{trigger}(.*?)$', content)
                if video_url_match:
                    video_url = self.extract_video_url(video_url_match.group(1))
                    if video_url:
                        content = self.get_video_download(video_url)
                        #reply = self.create_reply(ReplyType.VIDEO_URL, content)
                        reply = self.create_reply(ReplyType.TEXT, content)
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
                        return
            

        # 天气查询
        weather_match = re.match(r'^(?:(.{2,7}?)(?:市|县|区|镇)?|(\d{7,9}))(?:的)?天气$', content)
        if weather_match:
            # 如果匹配成功，提取第一个捕获组
            city_or_id = weather_match.group(1) or weather_match.group(2)
            if not self.alapi_token:
                self.handle_error("alapi_token not configured", "天气请求失败")
                reply = self.create_reply(ReplyType.TEXT, "请先配置alapi的token")
            else:
                content = self.get_weather(self.alapi_token, city_or_id, content)
                reply = self.create_reply(ReplyType.TEXT, content)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            return

    def extract_video_url(self, text):
        url_match = re.search(r'(http[s]?://\S+)', text)
        if url_match:
            return url_match.group(1)
        return None

    def get_help_text(self, verbose=False, **kwargs):
        short_help_text = " 发送特定指令以获取早报、热榜、查询天气、星座运势、快递信息等！"

        if not verbose:
            return short_help_text

        help_text = "📚 发送关键词获取特定信息！\n"

        # 娱乐和信息类
        help_text += "\n🎉 娱乐与资讯：\n"
        help_text += "  🌅 早报: 发送“早报”获取早报。\n"
        help_text += "  🐟 摸鱼: 发送“摸鱼”获取摸鱼人日历。\n"
        help_text += "  🔥 热榜: 发送“xx热榜”查看支持的热榜。\n"
        help_text += "  🔥 八卦: 发送“八卦”获取明星八卦。\n"

        # 查询类
        help_text += "\n🔍 查询工具：\n"
        help_text += "  🌦️ 天气: 发送“城市+天气”查天气，如“北京天气”。\n"
        help_text += "  📦 快递: 发送“快递+单号”查询快递状态。如“快递112345655”\n"
        help_text += "  🌌 星座: 发送星座名称查看今日运势，如“白羊座”。\n"

        return help_text

    def get_morning_news(self, alapi_token, morning_news_text_enabled):
        if not alapi_token:
            url = BASE_URL_VVHAN + "60s?type=json"
            payload = "format=json"
            headers = {'Content-Type': "application/x-www-form-urlencoded"}
            try:
                morning_news_info = self.make_request(url, method="POST", headers=headers, data=payload)
                if isinstance(morning_news_info, dict) and morning_news_info['success']:
                    if morning_news_text_enabled:
                        # 提取并格式化新闻
                        news_list = ["{}. {}".format(idx, news) for idx, news in enumerate(morning_news_info["data"][:-1], 1)]
                        formatted_news = f"☕ {morning_news_info['data']['date']}  今日早报\n"
                        formatted_news = formatted_news + "\n".join(news_list)
                        weiyu = morning_news_info["data"][-1].strip()
                        return f"{formatted_news}\n\n{weiyu}\n\n 图片url：{morning_news_info['imgUrl']}"
                    else:
                        return morning_news_info['imgUrl']
                else:
                    return self.handle_error(morning_news_info, '早报信息获取失败，可配置"alapi token"切换至 Alapi 服务，或者稍后再试')
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            url = BASE_URL_ALAPI + "zaobao"
            data = {
                "token": alapi_token,
                "format": "json"
            }
            headers = {'Content-Type': "application/x-www-form-urlencoded"}
            try:
                morning_news_info = self.make_request(url, method="POST", headers=headers, data=data)
                if isinstance(morning_news_info, dict) and morning_news_info.get('code') == 200:
                    img_url = morning_news_info['data']['image']
                    if morning_news_text_enabled:
                        news_list = morning_news_info['data']['news']
                        weiyu = morning_news_info['data']['weiyu']

                        # 整理新闻为有序列表
                        formatted_news = f"☕ {morning_news_info['data']['date']}  今日早报\n"
                        formatted_news = formatted_news + "\n".join(news_list)
                        # 组合新闻和微语
                        return f"{formatted_news}\n\n{weiyu}\n\n 图片url：{img_url}"
                    else:
                        return img_url
                else:
                    return self.handle_error(morning_news_info, "早报获取失败，请检查 token 是否有误")
            except Exception as e:
                return self.handle_error(e, "早报获取失败")

    def get_moyu_calendar(self):
        url = BASE_URL_VVHAN + "moyu?type=json"
        payload = "format=json"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        moyu_calendar_info = self.make_request(url, method="POST", headers=headers, data=payload)
        # 验证请求是否成功
        if isinstance(moyu_calendar_info, dict) and moyu_calendar_info['success']:
            return moyu_calendar_info['url']
        else:
            url = "https://dayu.qqsuu.cn/moyuribao/apis.php?type=json"
            payload = "format=json"
            headers = {'Content-Type': "application/x-www-form-urlencoded"}
            moyu_calendar_info = self.make_request(url, method="POST", headers=headers, data=payload)
            if isinstance(moyu_calendar_info, dict) and moyu_calendar_info['code'] == 200:
                moyu_pic_url = moyu_calendar_info['data']
                if self.is_valid_image_url(moyu_pic_url):
                    return moyu_pic_url
                else:
                    return "周末无需摸鱼，愉快玩耍吧"
            else:
                return "暂无可用“摸鱼”服务，认真上班"

    def get_hot_trends_A(self):
        url = "https://open.tophub.today/hot"
        data = self.make_request(url, "GET")
        if isinstance(data, dict) and 'data' in data:
            output = []
            items = data['data']['items']
            output.append(f'***今日热点***\n')
            for i, item in enumerate(items[:15], 1):
                title = item.get('title', '无标题')
                url = item.get('url', '无URL')
                views = item.get('views', '无浏览量')
                timestamp = int(item.get('time', 0))
                if timestamp > 0:
                    time_struct = time.localtime(timestamp)
                    formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time_struct)
                else:
                    formatted_time = '无时间信息'
                formatted_str = f"{i}. {title}  ({views})\n{url}\n更新时间: {formatted_time}\n"
                output.append(formatted_str)
            return "\n".join(output)
        else:
            return self.handle_error(data, "热榜获取失败，请稍后再试")

    def get_moyu_calendar_video(self):
        url = "https://dayu.qqsuu.cn/moyuribaoshipin/apis.php?type=json"
        payload = "format=json"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        moyu_calendar_info = self.make_request(url, method="POST", headers=headers, data=payload)
        # 验证请求是否成功
        if isinstance(moyu_calendar_info, dict) and moyu_calendar_info['code'] == 200:
            moyu_video_url = moyu_calendar_info['data']
            if self.is_valid_image_url(moyu_video_url):
                return moyu_video_url
        else:
            return "视频版没了，看看文字版吧"

    def get_horoscope(self, alapi_token, astro_sign: str, time_period: str = "today"):
        if not alapi_token:
            url = BASE_URL_VVHAN + "horoscope"
            params = {
                'type': astro_sign,
                'time': time_period
            }
            try:
                horoscope_data = self.make_request(url, "GET", params=params)
                if isinstance(horoscope_data, dict) and horoscope_data['success']:
                    data = horoscope_data['data']

                    result = (
                        f"{data['title']} ({data['time']}):\n\n"
                        f"💡【每日建议】\n宜：{data['todo']['yi']}\n忌：{data['todo']['ji']}\n\n"
                        f"📊【运势指数】\n"
                        f"总运势：{data['index']['all']}\n"
                        f"爱情：{data['index']['love']}\n"
                        f"工作：{data['index']['work']}\n"
                        f"财运：{data['index']['money']}\n"
                        f"健康：{data['index']['health']}\n\n"
                        f"🍀【幸运提示】\n数字：{data['luckynumber']}\n"
                        f"颜色：{data['luckycolor']}\n"
                        f"星座：{data['luckyconstellation']}\n\n"
                        f"✍【简评】\n{data['shortcomment']}\n\n"
                        f"📜【详细运势】\n"
                        f"总运：{data['fortunetext']['all']}\n"
                        f"爱情：{data['fortunetext']['love']}\n"
                        f"工作：{data['fortunetext']['work']}\n"
                        f"财运：{data['fortunetext']['money']}\n"
                        f"健康：{data['fortunetext']['health']}\n"
                    )

                    return result

                else:
                    return self.handle_error(horoscope_data, '星座信息获取失败，可配置"alapi token"切换至 Alapi 服务，或者稍后再试')

            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            # 使用 ALAPI 的 URL 和提供的 token
            url = BASE_URL_ALAPI + "star"
            payload = f"token={alapi_token}&star={astro_sign}"
            headers = {'Content-Type': "application/x-www-form-urlencoded"}
            try:
                horoscope_data = self.make_request(url, method="POST", headers=headers, data=payload)
                if isinstance(horoscope_data, dict) and horoscope_data.get('code') == 200:
                    data = horoscope_data['data']['day']

                    # 格式化并返回 ALAPI 提供的星座信息
                    result = (
                        f"📅 日期：{data['date']}\n\n"
                        f"💡【每日建议】\n宜：{data['yi']}\n忌：{data['ji']}\n\n"
                        f"📊【运势指数】\n"
                        f"总运势：{data['all']}\n"
                        f"爱情：{data['love']}\n"
                        f"工作：{data['work']}\n"
                        f"财运：{data['money']}\n"
                        f"健康：{data['health']}\n\n"
                        f"🔔【提醒】：{data['notice']}\n\n"
                        f"🍀【幸运提示】\n数字：{data['lucky_number']}\n"
                        f"颜色：{data['lucky_color']}\n"
                        f"星座：{data['lucky_star']}\n\n"
                        f"✍【简评】\n总运：{data['all_text']}\n"
                        f"爱情：{data['love_text']}\n"
                        f"工作：{data['work_text']}\n"
                        f"财运：{data['money_text']}\n"
                        f"健康：{data['health_text']}\n"
                    )
                    return result
                else:
                    return self.handle_error(horoscope_data, "星座获取信息获取失败，请检查 token 是否有误")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")

    def get_exchange_rate(self, bank_name, currency_name, date):
        # 查找映射字典以获取API参数
        bank_name_en = bank_names.get(bank_name, None)
        currency_name_en = currency_names.get(currency_name, None)
        payload = f"app=finance.rate_cnyquot_history&curno={currency_name_en}&bankno={bank_name_en}&appkey=72058&sign=4aaae5cd8d1be6759352edba53e8dff1&format=json"
        if date:
            payload += f"&date={date}"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        if bank_name_en is not None:
            url = "https://sapi.k780.com/"
            try:
                response = requests.request("POST", url, data=payload, headers=headers)
                data = response.json()
                if data['success']:
                    result = data['result']['lists']
                    latest = result[0]
                    output = [f"**{bank_name}{currency_name}汇率查询**\n最新更新时间：{latest['upymd']} {latest['uphis']}\n现汇买入价：{latest['se_buy']}\n现汇卖出价：{latest['se_sell']}\n\n***主要时点后第一个报价*** \n| 时间 | 现汇买入价 | 现汇卖出价 | "]
                    target_times = ["00:00", "09:30", "09:59", "10:00", "10:30"]
                    seen_times = set()
                    sorted_result = sorted(result, key=lambda x: x['uphis'])
                    for target_time in target_times:
                        for item in sorted_result:
                            time = item['uphis'][:5]
                            if time >= target_time and target_time not in seen_times:
                                seen_times.add(target_time)
                                output.append(f"| {item['uphis']} | {item['se_buy']} | {item['se_sell']} | ")
                                break
                    return "\n".join(output)
                else:
                    return self.handle_error(data, "汇率获取失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            supported_bank_names = "/".join(bank_names.keys())
            supported_currency_names = "/".join(currency_names.keys())
            final_output = (
                f"👉 已支持的银行有：\n\n    {supported_bank_names}\n"
                f"👉 已支持的币种有：\n\n    {supported_currency_names}\n"
                f"\n📝 请按照以下格式发送：\n    银行+币种+汇率  例如：中行美元汇率"
                f"\n📝 历史查询末尾加日期：\n    例如：中行美元汇率20240113"
            )
            return final_output

    def get_daily_rate(self,input_values):
            # 定义要查询的汇率列表
        exchange_rates = [
            {"bank_name": "中行", "currency_name": "USD", "target_time": "09:30", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "USD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "USD", "target_time": "10:30", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "EUR", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "HKD", "target_time": "09:30", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "HKD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "AUD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "JPY", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "CHF", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "SGD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "GBP", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "中行", "currency_name": "USD", "target_time": "00:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "USD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "EUR", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "HKD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "AUD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "JPY", "target_time": "10:00", "divide_by": 100000},
            {"bank_name": "交行", "currency_name": "CHF", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "SGD", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "交行", "currency_name": "GBP", "target_time": "10:00", "divide_by": 100},
            {"bank_name": "工行", "currency_name": "USD", "target_time": "10:00", "divide_by": 100},
        ]

        # 逐个查询汇率并格式化输出
        current_datetime = datetime.now()
        current_datetime_str = current_datetime.strftime("%Y-%m-%d %H:%M")
        results = [f"📅 {current_datetime_str} 查询结果：\n🟢 代表数据一致 \n🔴 代表数据不一致"]
        for i, exchange_rate in enumerate(exchange_rates):
            bank_name = exchange_rate["bank_name"]
            currency_name = exchange_rate["currency_name"]
            target_time = exchange_rate["target_time"]
            divide_by = exchange_rate["divide_by"]
            rate_str = input_values[i].strip()  # 获取对应汇率输入值

            # 查找映射字典以获取API参数
            bank_name_en = bank_names.get(bank_name, None)
            payload = f"app=finance.rate_cnyquot_history&curno={currency_name}&bankno={bank_name_en}&appkey=72058&sign=4aaae5cd8d1be6759352edba53e8dff1&format=json"
            headers = {'Content-Type': "application/x-www-form-urlencoded"}

            # 发送请求并处理响应
            if bank_name is not None:
                url = "https://sapi.k780.com/"
                try:
                    response = requests.request("POST", url, data=payload, headers=headers)
                    data = response.json()
                    # 解析和格式化数据
                    if data['success']:
                        result = data['result']['lists']
                        sorted_result = sorted(result, key=lambda x: x['uphis'])
                        found = False
                        for item in sorted_result:
                            time = item['uphis'][:5]
                            if time >= target_time:
                                rate = Decimal(item['se_sell']) / divide_by
                                rate = rate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
                                rate_str = str(rate).rstrip('0').rstrip('.')  # 删除多余的零和小数点
                                input_value_decimal = Decimal(input_values[i]).quantize(Decimal('.000001'), rounding=ROUND_HALF_UP)
                                if rate == input_value_decimal:
                                    results.append(f"🟢 {bank_name} {target_time} {currency_name}: {rate_str}")
                                else:
                                    results.append(f"🔴 {bank_name} {target_time} {currency_name}: {rate_str}\n📌 数据不一致，ERP系统数据为 {input_values[i]}")
                                found = True
                                break
                        if not found:
                            results.append(f"{bank_name} {target_time} {currency_name}: 未取得数据")
                    else:
                        print("汇率获取失败，请稍后再试")
                except Exception as e:
                    print("出错啦，稍后再试")
            else:
                print("不支持的银行或货币")

        # 返回结果列表
        return '\n'.join(results)

    def get_hot_trends(self, hot_trends_type):
        # 查找映射字典以获取API参数
        hot_trends_type_en = hot_trend_types.get(hot_trends_type, None)
        payload = f"token=Pv9NigNNblo6nxCs&type={hot_trends_type_en}"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        if hot_trends_type_en is not None:
            url = "https://v2.alapi.cn/api/tophub"
            try:
                response = requests.request("POST", url, data=payload, headers=headers)
                data = response.json()
                if data['code'] == 200:
                    output = [f"热榜名称：{data['data']['name']}，更新时间：{data['data']['last_update']}"]
                    for i, item in enumerate(data['data']['list'][:10], start=1):
                        title = item['title']
                        link = item['link']
                        other = item.get('other', '未知热度')  # 使用get以避免KeyError
                        output.append(f"{i}. {title} ({other})\nURL: {link}")
                    return "\n".join(output)
                else:
                    return self.handle_error(data, "热榜获取失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            supported_types = "/".join(hot_trend_types.keys())
            final_output = (
                f"👉 已支持的类型有：\n\n    {supported_types}\n"
                f"\n📝 请按照以下格式发送：\n    类型+热榜  例如：微博热榜"
            )
            return final_output

    def get_hot_trends_d(self, hot_trends_type_d):
        # 查找映射字典以获取API参数
        hot_trends_type_en_d = hot_trend_types_d.get(hot_trends_type_d, None)
        if hot_trends_type_en_d is not None:
            url = BASE_URL_VVHAN + "hotlist?type=" + hot_trends_type_en_d
            try:
                data = self.make_request(url, "GET")
                if isinstance(data, dict) and data['success'] == True:
                    output = []
                    topics = data['data']
                    output.append(f'更新时间：{data["update_time"]}\n')
                    for i, topic in enumerate(topics[:15], 1):
                        hot = topic.get('hot', '无热度参数, 0')
                        formatted_str = f"{i}. {topic['title']} ({hot} 浏览)\nURL: {topic['url']}\n"
                        output.append(formatted_str)
                    return "\n".join(output)
                else:
                    return self.handle_error(data, "热点获取失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            supported_types = "/".join(hot_trend_types_d.keys())
            final_output = (
                f"👉 已支持的类型有：\n\n    {supported_types}\n"
                f"\n📝 请按照以下格式发送：\n    类型+热点  例如：微博热点"
            )
            return final_output

    def get_starinfo(self, starname):
        # 查找映射字典以获取API参数
        if starname is not None:
            url = "https://apis.tianapi.com/starinfo/index?key=e106437569b8fa19f1527c9939022e60&name=" + starname
            try:
                data = self.make_request(url, "GET")
                if isinstance(data, dict) and data['code'] == 200 and data['msg'] == 'success':
                    star_list = data['result']['list']
                    output = []
                    for star_data in star_list:
                        info = [
                            f"姓名：{star_data.get('name', '未知')}",
                            f"性别：{star_data.get('sex', '未知')}",
                            f"国籍：{star_data.get('nationality', '未知')}",
                            f"出生日期：{star_data.get('birthDate', '未知')}",
                            f"职业：{star_data.get('occupation', '未知')}",
                            f"身高：{star_data.get('high', '未知')}",
                            f"体重：{star_data.get('weight', '未知')}",
                            f"描述：{star_data.get('desc', '未知')}",
                            f"出生地：{star_data.get('nativePlace', '未知')}",
                            f"毕业院校：{star_data.get('school', '未知')}",
                            f"所属公司：{star_data.get('company', '未知')}",
                            f"星座：{star_data.get('constellation', '未知')}",
                            f"习惯：{star_data.get('habit', '未知')}"
                        ]
                        output.append("\n".join(info))
                    return "\n".join(output)
                else:
                    return self.handle_error(data, "信息获取失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            final_output = (
                f"👉 请按照以下格式发送：搜人+人名 例如：搜人刘德华"
            )
            return final_output

    def get_starpic(self, starname):
        # 查找映射字典以获取API参数
        if starname is not None:
            url = "https://apis.tianapi.com/starinfo/index?key=e106437569b8fa19f1527c9939022e60&name=" + starname
            try:
                data = self.make_request(url, "GET")
                if isinstance(data, dict) and data['code'] == 200 and data['msg'] == 'success':
                    star_list = data['result']['list']
                    if star_list:
                        first_star = star_list[0]
                        first_image_url = first_star.get('imageURL', '未知')
                        return first_image_url
                else:
                    return self.handle_error(data, "图片获取失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "出错啦，稍后再试")
        else:
            final_output = (
                f"👉 请按照以下格式发送：搜图+人名 例如：搜图刘德华"
            )
            return final_output

    def get_video_summary(self, video_url, trigger):
        # 查找映射字典以获取API参数
        if video_url is not None:
            headers = {
                'Content-Type': 'application/json'
            }
            payload_params = {
                "url": video_url,
                "includeDetail": True,
                "limitation": {
                    "maxDuration": 900
                },
                "promptConfig": {
                    "showEmoji": True,
                    "showTimestamp": True,
                    #"outlineLevel": 1,
                    #"sentenceNumber": 6,
                    #"detailLevel": 700,
                    "outputLanguage": "zh-CN"
                }
            }
            payload = json.dumps(payload_params)
            try:
                api_url = "https://bibigpt.co/api/open/yeiP5PHcs26a"
                response = requests.request("POST",api_url, headers=headers, data=payload)
                response.raise_for_status()
                data = json.loads(response.text)
                if isinstance(data, dict) and data['success'] == True:
                    if trigger == "视频总结":
                        summary = data["summary"].split("详细版（支持对话追问）")[0].replace("## 摘要\n", "📌总结：\n").replace("## 总结\n", "📌总结：\n")
                        return f'{summary}'
                    elif trigger == "视频数据":
                        return f'：{data}\n'
                    elif trigger == "视频字幕":
                        summary_content = data['detail']['title']
                        formatted_summary = f'📌字幕：\n{summary_content}\n'
                        result = formatted_summary
                        subtitles = []
                        for subtitle in data['detail']['subtitlesArray']:
                            start_time = int(subtitle['startTime'])
                            minutes = start_time // 60
                            seconds = start_time % 60
                            formatted_start_time = f"{minutes}:{seconds:02d}" if minutes > 0 else f"{seconds:02d}"
                            subtitles.append(f"[{formatted_start_time}] {subtitle['text']}")
                        result += '\n'.join(subtitles)
                        return result
                else:
                    return self.handle_error(data, "视频总结失败，请稍后再试")
            except Exception as e:
                return self.handle_error(e, "视频总结出错啦，稍后再试")

    def get_video_download(self, video_url):
        api_url = "https://v2.alapi.cn/api/video/url"
        payload = f"token=Pv9NigNNblo6nxCs&url={video_url}"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        # 重试 10 次
        for _ in range(2):
            try:
                response = requests.request("POST", api_url, data=payload, headers=headers)
                response.raise_for_status()  # 如果状态码是 4xx 或 5xx，抛出 HTTPError 异常
            except requests.exceptions.HTTPError as errh:
                return self.handle_error(errh, "地址解析失败：HTTP Error")
            except requests.exceptions.ConnectionError as errc:
                return self.handle_error(errc, "地址解析失败：Error Connecting")
            except requests.exceptions.Timeout as errt:
                return self.handle_error(errt, "地址解析失败：Timeout Error")
            except requests.exceptions.RequestException as err:
                return self.handle_error(err, "地址解析失败：Something went wrong")

            if response.status_code == 200:
                response_json = response.json()
                if 'data' in response_json and response_json['data'] is not None and 'video_url' in response_json['data']:
                    #return response_json['data']['video_url']
                    return "标题：" + response_json['data']['title'] + "\n" + response_json['data']['video_url']

            # 如果响应码不是 200，等待 2 秒然后重试
            time.sleep(10)
        return None

    def query_express_info(self, alapi_token, tracking_number, com="", order="asc"):
        url = BASE_URL_ALAPI + "kd"
        payload = f"token={alapi_token}&number={tracking_number}&com={com}&order={order}"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}

        try:
            response_json = self.make_request(url, method="POST", headers=headers, data=payload)

            if not isinstance(response_json, dict) or response_json is None:
                return f"查询失败：api响应为空"
            code = response_json.get("code", None)
            if code != 200:
                msg = response_json.get("msg", "未知错误")
                self.handle_error(msg, f"错误码{code}")
                return f"查询失败，{msg}"
            data = response_json.get("data", None)
            formatted_result = [
                f"快递编号：{data.get('nu')}",
                f"快递公司：{data.get('com')}",
                f"状态：{data.get('status_desc')}",
                "状态信息："
            ]
            for info in data.get("info"):
                time_str = info.get('time')[5:-3]
                formatted_result.append(f"{time_str} - {info.get('status_desc')}\n    {info.get('content')}")

            return "\n".join(formatted_result)

        except Exception as e:
            return self.handle_error(e, "快递查询失败")

    def get_weather(self, alapi_token, city_or_id: str, content):
        url = BASE_URL_ALAPI + 'tianqi'
        # 判断使用id还是city请求api
        if city_or_id.isnumeric():  # 判断是否为纯数字，也即是否为 city_id
            params = {
                'city_id': city_or_id,
                'token': f'{alapi_token}'
            }
        else:
            city_info = self.check_multiple_city_ids(city_or_id)
            if city_info:
                data = city_info['data']
                formatted_city_info = "\n".join(
                    [f"{idx + 1}) {entry['province']}--{entry['leader']}, ID: {entry['city_id']}"
                     for idx, entry in enumerate(data)]
                )
                return f"查询 <{city_or_id}> 具有多条数据：\n{formatted_city_info}\n请使用id查询，发送“id天气”"

            params = {
                'city': city_or_id,
                'token': f'{alapi_token}'
            }
        try:
            weather_data = self.make_request(url, "GET", params=params)
            if isinstance(weather_data, dict) and weather_data.get('code') == 200:
                data = weather_data['data']
                update_time = data['update_time']
                dt_object = datetime.strptime(update_time, "%Y-%m-%d %H:%M:%S")
                formatted_update_time = dt_object.strftime("%m-%d %H:%M")
                # Basic Info
                if not city_or_id.isnumeric() and data['city'] not in content:  # 如果返回城市信息不是所查询的城市，重新输入
                    return "输入不规范，请输<国内城市+天气>，比如 '成都天气'"
                formatted_output = []
                basic_info = (
                    f"🏙️ 城市: {data['city']} ({data['province']})\n"
                    f"🕒 更新: {formatted_update_time}\n"
                    f"🌦️ 天气: {data['weather']}\n"
                    f"🌡️ 温度: ↓{data['min_temp']}℃| 现{data['temp']}℃| ↑{data['max_temp']}℃\n"
                    f"🌬️ 风向: {data['wind']}\n"
                    f"💦 湿度: {data['humidity']}\n"
                    f"🌅 日出/日落: {data['sunrise']} / {data['sunset']}\n"
                )
                formatted_output.append(basic_info)


                # Clothing Index,处理部分县区穿衣指数返回null
                chuangyi_data = data.get('index', {}).get('chuangyi', {})
                if chuangyi_data:
                    chuangyi_level = chuangyi_data.get('level', '未知')
                    chuangyi_content = chuangyi_data.get('content', '未知')
                else:
                    chuangyi_level = '未知'
                    chuangyi_content = '未知'

                chuangyi_info = f"👚 穿衣指数: {chuangyi_level} - {chuangyi_content}\n"
                formatted_output.append(chuangyi_info)
                # Next 7 hours weather
                ten_hours_later = dt_object + timedelta(hours=10)

                future_weather = []
                for hour_data in data['hour']:
                    forecast_time_str = hour_data['time']
                    forecast_time = datetime.strptime(forecast_time_str, "%Y-%m-%d %H:%M:%S")

                    if dt_object < forecast_time <= ten_hours_later:
                        future_weather.append(f"     {forecast_time.hour:02d}:00 - {hour_data['wea']} - {hour_data['temp']}°C")

                future_weather_info = "⏳ 未来10小时的天气预报:\n" + "\n".join(future_weather)
                formatted_output.append(future_weather_info)

                # Alarm Info
                if data.get('alarm'):
                    alarm_info = "⚠️ 预警信息:\n"
                    for alarm in data['alarm']:
                        alarm_info += (
                            f"🔴 标题: {alarm['title']}\n"
                            f"🟠 等级: {alarm['level']}\n"
                            f"🟡 类型: {alarm['type']}\n"
                            f"🟢 提示: \n{alarm['tips']}\n"
                            f"🔵 内容: \n{alarm['content']}\n\n"
                        )
                    formatted_output.append(alarm_info)

                return "\n".join(formatted_output)
            else:
                return self.handle_error(weather_data, "获取失败，请查看服务器log")

        except Exception as e:
            return self.handle_error(e, "获取天气信息失败")

    def get_mx_bagua(self):
        url = "https://dayu.qqsuu.cn/mingxingbagua/apis.php?type=json"
        payload = "format=json"
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        bagua_info = self.make_request(url, method="POST", headers=headers, data=payload)
        # 验证请求是否成功
        if isinstance(bagua_info, dict) and bagua_info['code'] == 200:
            bagua_pic_url = bagua_info["data"]
            if self.is_valid_image_url(bagua_pic_url):
                return bagua_pic_url
            else:
                return "周末不更新，请微博吃瓜"
        else:
            logger.error(f"错误信息：{bagua_info}")
            return "暂无明星八卦，吃瓜莫急"

    def make_request(self, url, method="GET", headers=None, params=None, data=None, json_data=None):
        try:
            if method.upper() == "GET":
                response = requests.request(method, url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = requests.request(method, url, headers=headers, data=data, json=json_data)
            else:
                return {"success": False, "message": "Unsupported HTTP method"}

            return response.json()
        except Exception as e:
            return e


    def create_reply(self, reply_type, content):
        reply = Reply()
        reply.type = reply_type
        reply.content = content
        return reply

    def handle_error(self, error, message):
        logger.error(f"{message}，错误信息：{error}")
        return message

    def is_valid_url(self, url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def is_valid_image_url(self, url):
        try:
            response = requests.head(url)  # Using HEAD request to check the URL header
            # If the response status code is 200, the URL exists and is reachable.
            return response.status_code == 200
        except requests.RequestException as e:
            # If there's an exception such as a timeout, connection error, etc., the URL is not valid.
            return False

    def load_city_conditions(self):
        if self.condition_2_and_3_cities is None:
            try:
                json_file_path = os.path.join(os.path.dirname(__file__), 'duplicate-citys.json')
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    self.condition_2_and_3_cities = json.load(f)
            except Exception as e:
                return self.handle_error(e, "加载condition_2_and_3_cities.json失败")


    def check_multiple_city_ids(self, city):
        self.load_city_conditions()
        city_info = self.condition_2_and_3_cities.get(city, None)
        if city_info:
            return city_info
        return None


ZODIAC_MAPPING = {
        '白羊座': 'aries',
        '金牛座': 'taurus',
        '双子座': 'gemini',
        '巨蟹座': 'cancer',
        '狮子座': 'leo',
        '处女座': 'virgo',
        '天秤座': 'libra',
        '天蝎座': 'scorpio',
        '射手座': 'sagittarius',
        '摩羯座': 'capricorn',
        '水瓶座': 'aquarius',
        '双鱼座': 'pisces'
    }

bank_names = {
    "中行": "BOC",
    "建行": "CCB",
    "农行": "ABC",
    "工行": "ICBC",
    "交行": "BCM",
    "光大": "CEB"

    }

currency_names = {
    "美元": "USD",
    "欧元": "EUR",
    "港币": "HKD",
    "澳元": "AUD",
    "法郎": "CHF",
    "新加坡元": "SGD",
    "日元": "JPY",
    "英镑": "GBP"

    }

hot_trend_types_d = {
    "微博": "wbHot",
    "虎扑": "huPu",
    "知乎": "zhihuHot",
    "哔哩哔哩": "bili",
    "36氪": "36Ke",
    "抖音": "douyinHot",
    "少数派": "ssPai",
    "IT最新": "itNews",
    "IT科技": "itInfo"

}

hot_trend_types = {
    "知乎": "zhihu",
    "微博": "weibo",
    "微信": "weixin",
    "百度": "baidu",
    "今日": "toutiao",
    "网易": "163",
    "新浪": "xl",
    "36氪": "36k",
    "历史上的今天": "hitory",
    "少数派": "sspai",
    "CSDN": "csdn",
    "掘金": "juejin",
    "哔哩哔哩": "bilibili",
    "抖音": "douyin",
    "吾爱破解": "52pojie",
    "V2ex": "v2ex",
    "全球主机论坛": "hostloc"

}
