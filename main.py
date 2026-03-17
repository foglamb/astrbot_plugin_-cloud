from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import aiohttp
import json
import time
import asyncio
from typing import Optional

@register("cloud_submit", "OneTHos", "移动云盘代挂及CK登录提交插件", "1.0.0")
class CloudSubmitPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.admin_token: Optional[str] = None
        self.token_expires_at: int = 0
        
        # 从配置中读取API地址，不允许默认值包含真实IP
        self.base_url = self.config.get("cloud_api_url")
        if not self.base_url:
            raise ValueError("配置缺失：请在插件配置中设置 'cloud_api_url' 字段，例如 http://your-server:port")

        self.login_url = f"{self.base_url}/api/api/auth/login"
        # 新增CK登录API地址
        self.ck_login_url = f"{self.base_url}/api/api/accounts"
        # 新增短信发送API地址
        self.sms_send_url = f"{self.base_url}/api/api/accounts/sms/send"
        # 新增短信验证码验证API地址
        self.sms_verify_url = f"{self.base_url}/api/api/accounts/sms/verify"
        # 新增短信状态检查API地址
        self.sms_status_url = f"{self.base_url}/api/api/accounts/sms/status/"
        # 新增dashboard API地址
        self.dashboard_url = f"{self.base_url}/api/api/admin/dashboard"
        
        # 从配置中读取管理员账号信息，不允许默认账号密码
        admin_account = self.config.get("admin_account")
        if not admin_account:
            raise ValueError("配置缺失：请在插件配置中设置 'admin_account' 字段，包含 username 和 password")
        self.username = admin_account.get("username")
        self.password = admin_account.get("password")
        if not self.username or not self.password:
            raise ValueError("配置错误：'admin_account' 必须包含非空的 'username' 和 'password'")
        
        # 新增task_id缓存字典
        self.phone_task_map = {}

    async def initialize(self):
        """初始化插件，获取管理员 token"""
        await self._refresh_admin_token()

    async def _refresh_admin_token(self) -> bool:
        """刷新管理员 token"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/login",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }
                data = {
                    "username": self.username,
                    "password": self.password
                }
                
                async with session.post(self.login_url, 
                                      headers=headers, 
                                      json=data,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        self.admin_token = result.get("token")
                        self.token_expires_at = result.get("expires_at", 0)
                        logger.info(f"Successfully refreshed admin token. Expires at: {self.token_expires_at}")
                        return True
                    else:
                        logger.error(f"Failed to refresh admin token. Status: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error refreshing admin token: {e}")
            return False

    async def get_valid_admin_token(self) -> Optional[str]:
        """获取有效的管理员 token，如果过期则自动刷新"""
        current_time = int(time.time())
        if not self.admin_token or self.token_expires_at - current_time < 300:
            success = await self._refresh_admin_token()
            if not success:
                return None
        return self.admin_token

    async def _submit_ck_login(self, phone: str, auth: str, remark: str = "") -> bool:
        """提交CK登录请求"""
        token = await self.get_valid_admin_token()
        if not token:
            logger.error("No valid admin token available for CK login")
            return False
            
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Authorization": f"Bearer {token}",
                    "Connection": "keep-alive",
                    "Content-Type": "application/json",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/accounts",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }
                data = {
                    "phone": phone,
                    "auth": auth,
                    "remark": remark
                }
                
                async with session.post(self.ck_login_url,
                                      headers=headers,
                                      json=data,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"CK login successful for phone {phone}, result: {result}")
                        return True
                    else:
                        logger.error(f"CK login failed for phone {phone}. Status: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Error during CK login for phone {phone}: {e}")
            return False

    # 新增检查短信状态方法
    async def _check_sms_status(self, phone: str) -> dict:
        """检查短信验证码状态"""
        token = await self.get_valid_admin_token()
        if not token:
            logger.error("No valid admin token available for SMS status check")
            return {"success": False, "message": "获取管理员 token 失败"}

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Authorization": f"Bearer {token}",
                    "Connection": "keep-alive",
                    "Referer": f"{self.base_url}/accounts",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }

                async with session.get(f"{self.sms_status_url}{phone}",
                                      headers=headers,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"SMS status check for phone {phone}, result: {result}")
                        data = result.get("data", {})
                        status = data.get("status", "")
                        message = data.get("message", "")

                        if status == "completed":
                            return {"success": True, "status": "completed", "message": message}
                        elif status == "failed":
                            # 如果状态为failed，返回具体的错误消息
                            return {"success": False, "status": "failed", "message": message}
                        else:
                            # 其他状态（如processing）继续等待
                            return {"success": False, "status": status, "message": message}
                    else:
                        logger.error(f"Failed to check SMS status for phone {phone}. Status: {response.status}")
                        return {"success": False, "message": f"检查状态失败，状态码: {response.status}"}
        except Exception as e:
            logger.error(f"Error during SMS status check for phone {phone}: {e}")
            return {"success": False, "message": f"检查状态过程中出现错误: {str(e)}"}

    # 新增发送短信验证码方法
    async def _send_sms_code(self, phone: str) -> dict:
        """发送短信验证码"""
        token = await self.get_valid_admin_token()
        if not token:
            logger.error("No valid admin token available for SMS sending")
            return {"success": False, "message": "获取管理员 token 失败"}
            
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Authorization": f"Bearer {token}",
                    "Connection": "keep-alive",
                    "Content-Type": "application/json",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/accounts",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }
                data = {
                    "phone": phone
                }
                
                async with session.post(self.sms_send_url,
                                      headers=headers,
                                      json=data,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"SMS code sent successfully for phone {phone}, result: {result}")
                        # 存储task_id到缓存
                        task_id = result.get("data", {}).get("task_id")
                        if task_id:
                            self.phone_task_map[phone] = task_id

                        # 轮询等待状态变为completed
                        max_retries = 10  # 最多重试10次
                        retry_delay = 1   # 每次等待1秒

                        for i in range(max_retries):
                            status_result = await self._check_sms_status(phone)
                            if status_result["success"] and status_result["status"] == "completed":
                                return {"success": True, "message": "验证码已发送", "task_id": task_id}
                            elif status_result["status"] == "failed":
                                # 如果状态为failed，立即返回错误消息
                                return {"success": False, "message": f"验证码发送失败: {status_result['message']}"}
                            elif i < max_retries - 1:  # 不是最后一次重试且状态不是failed
                                await asyncio.sleep(retry_delay)

                        # 轮询结束后仍未completed
                        return {"success": False, "message": f"验证码发送但状态检查超时，最后状态: {status_result.get('status', 'unknown')}"}
                    else:
                        logger.error(f"Failed to send SMS code for phone {phone}. Status: {response.status}")
                        if response.status == 429:
                            return {"success": False, "message": "请求过于频繁，请稍后再试"}
                        else:
                            return {"success": False, "message": f"发送失败，状态码: {response.status}"}
        except Exception as e:
            logger.error(f"Error during SMS sending for phone {phone}: {e}")
            return {"success": False, "message": f"发送过程中出现错误: {str(e)}"}

    # 新增提交短信验证码方法
    async def _submit_sms_login(self, phone: str, sms_code: str, remark: str = "") -> bool:
        """提交短信验证码登录请求"""
        token = await self.get_valid_admin_token()
        if not token:
            logger.error("No valid admin token available for SMS verification")
            return False
            
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Authorization": f"Bearer {token}",
                    "Connection": "keep-alive",
                    "Content-Type": "application/json",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/accounts",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }
                data = {
                    "phone": phone,
                    "sms_code": sms_code,
                    "remark": remark
                }
                
                # 记录完整的请求数据
                logger.info(f"Sending SMS verification request for phone {phone}, data: {data}")
                
                async with session.post(self.sms_verify_url,
                                      headers=headers,
                                      json=data,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"SMS verification successful for phone {phone}, result: {result}")
                        return True
                    else:
                        # 尝试读取响应内容以获取更多错误信息
                        try:
                            error_result = await response.json()
                            logger.error(f"SMS verification failed for phone {phone}. Status: {response.status}, Response: {error_result}")
                        except:
                            response_text = await response.text()
                            logger.error(f"SMS verification failed for phone {phone}. Status: {response.status}, Response text: {response_text}")
                        return False
        except Exception as e:
            logger.error(f"Error during SMS verification for phone {phone}: {e}")
            return False

    @filter.command("submit")
    async def submit_cloud_task(self, event: AstrMessageEvent):
        """提交移动云盘代挂任务"""
        user_name = event.get_sender_name()
        message_str = event.message_str
        # 这里应该实现实际的提交逻辑
        logger.info(f"Received submit request from {user_name}: {message_str}")
        yield event.plain_result(f"已收到您的移动云盘代挂提交请求，内容为: {message_str}")

    @filter.command("gettoken")
    async def get_token_command(self, event: AstrMessageEvent):
        """获取当前有效的管理员 token"""
        token = await self.get_valid_admin_token()
        if token:
            yield event.plain_result("已成功获取有效的管理员 token")
        else:
            yield event.plain_result("获取管理员 token 失败")

    @filter.regex(r"^云盘代挂$")
    async def handle_menu(self, event: AstrMessageEvent):
        """处理「云盘代挂」指令，返回使用教程"""
        tutorial = (
            "📌 移动云盘代挂与登录使用说明：\n"
            "1️⃣ CK 登录（手动抓authorization）：\n"
            "   发送：云盘登录1#手机号#auth\n"
            "2️⃣ 短信验证码登录：\n"
            "   第一步：发送 云盘登录2#手机号 获取验证码\n"
            "   第二步：发送 云盘登录2#手机号#验证码 完成登录\n"
            "3️⃣ 云盘查询：\n"
            "   发送：云盘查询 查看您的账号信息\n"
            "   云盘注册链接：http://88fa.cn/K7.先链接注册再下载app登录后提交"
        )
        yield event.plain_result(tutorial)

    @filter.regex(r"^云盘登录1#([^#]+)#(.+)$")
    async def handle_ck_login(self, event: AstrMessageEvent):
        """处理CK登录请求：云盘登录1#手机号#auth"""
        user_name = event.get_sender_name()
        message_str = event.message_str
        
        # 手动解析参数
        parts = message_str.split('#')
        if len(parts) >= 3:
            phone = parts[1]
            auth = parts[2]
            logger.info(f"Received CK login request from {user_name}: phone={phone}, auth={auth}")
            
            # 使用用户QQ号作为remark
            user_id = event.get_sender_id()
            remark = str(user_id)
            success = await self._submit_ck_login(phone, auth, remark=remark)
            if success:
                yield event.plain_result("CK登录提交成功！")
            else:
                yield event.plain_result("CK登录提交失败，请稍后重试或联系管理员")
        else:
            yield event.plain_result("CK登录格式错误，请使用：云盘登录1#手机号#auth")

    @filter.regex(r"^云盘登录2#(.+)$")
    async def handle_sms_login(self, event: AstrMessageEvent):
        """处理短信验证码登录请求：云盘登录2#手机号 或 云盘登录2#手机号#验证码"""
        user_name = event.get_sender_name()
        message_str = event.message_str
        
        # 检查是否包含两个#，即是否为验证码提交格式
        if message_str.count('#') == 2:
            parts = message_str.split('#')
            phone = parts[1]
            code = parts[2]
            logger.info(f"Received SMS verification request from {user_name}: phone={phone}, code={code}")
            
            # 使用用户QQ号作为remark
            user_id = event.get_sender_id()
            remark = str(user_id)
            success = await self._submit_sms_login(phone, code, remark=remark)
            if success:
                yield event.plain_result("短信验证码登录成功！")
            else:
                yield event.plain_result("短信验证码登录失败，请检查验证码是否正确或稍后重试")
        else:
            # 原有的发送验证码逻辑
            # 从消息中提取手机号（去掉"云盘登录2#"前缀）
            phone = message_str.split('#', 1)[1] if '#' in message_str else ""
            if not phone:
                yield event.plain_result("手机号格式错误，请使用：云盘登录2#手机号")
                return
                
            logger.info(f"Received SMS login request from {user_name}: phone={phone}")
            
            result = await self._send_sms_code(phone)
            if result["success"]:
                yield event.plain_result(f"验证码已发送，请回复「云盘登录2#{phone}#验证码」完成登录。")
            else:
                yield event.plain_result(f"发送验证码失败：{result['message']}")

    async def _get_dashboard_data(self) -> Optional[dict]:
        """获取dashboard数据"""
        token = await self.get_valid_admin_token()
        if not token:
            logger.error("No valid admin token available for dashboard data")
            return None
            
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Authorization": f"Bearer {token}",
                    "Connection": "keep-alive",
                    "Referer": f"{self.base_url}/dashboard",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
                }
                
                async with session.get(self.dashboard_url,
                                      headers=headers,
                                      ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Successfully fetched dashboard data")
                        return result
                    else:
                        logger.error(f"Failed to fetch dashboard data. Status: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error during fetching dashboard data: {e}")
            return None

    def _mask_phone(self, phone: str) -> str:
        """对手机号进行脱敏处理"""
        if len(phone) >= 7:
            return phone[:3] + "***" + phone[-4:]
        return phone

    @filter.regex(r"^云盘查询$")
    async def handle_cloud_query(self, event: AstrMessageEvent):
        """处理云盘查询请求"""
        user_id = event.get_sender_id()
        user_qq = str(user_id)
        logger.info(f"Received cloud query request from QQ: {user_qq}")
        
        # 获取dashboard数据
        dashboard_data = await self._get_dashboard_data()
        if not dashboard_data:
            yield event.plain_result("获取云盘数据失败，请稍后重试或联系管理员")
            return
            
        # 从响应中提取account_ranking
        account_ranking = dashboard_data.get("data", {}).get("account_ranking", [])
        if not account_ranking:
            yield event.plain_result("未找到您的云盘账号信息")
            return
            
        # 筛选当前用户的账号
        user_accounts = [acc for acc in account_ranking if acc.get("remark") == user_qq]
        if not user_accounts:
            yield event.plain_result("未找到您的云盘账号信息")
            return
            
        # 构建回复消息
        messages = []
        for account in user_accounts:
            phone = account.get("phone", "")
            masked_phone = self._mask_phone(phone)
            cloud_count = account.get("cloud_count", 0)
            today_gained = account.get("today_gained", 0)
            signed_in = "已签到" if today_gained > 0 else "未签到"
            
            msg = (
                "=====账号信息=====\n"
                f"👤 账号: {user_qq}\n"
                f"📱 手机: {masked_phone}\n"
                f"💰 当前云朵: {cloud_count}\n"
                f"🔥 今日云朵: {today_gained}\n"
                f"✅ 签到状态: {signed_in}\n"
                "=================="
            )
            messages.append(msg)
            
        # 合并所有账号信息
        final_message = "\n\n".join(messages)
        yield event.plain_result(final_message)

    async def terminate(self):
        """插件销毁时清理资源"""
        self.admin_token = None
        self.token_expires_at = 0
        self.phone_task_map.clear()
