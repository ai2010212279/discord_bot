from discord.ext import commands
from discord.ext.commands.context import Context
from discord import Object as discord_obj
from discord.channel import TextChannel
import sqlite3 as db
import yaml
import os 
import pandas as pd
# 待优化点: 
# 数据库连接替换为数据库连接池

bot = commands.Bot(command_prefix=">")
global config_file,force_stop_batch_send_msg 


#从文件中获取sql
def load_sql_from_file(path: str):
    f = open(path, "r")
    lines = f.readlines()
    f.close()
    sql = "".join(lines)
    return sql


def find_index(cur: db.Cursor):
    keys = [x[0] for x in cur.description]
    map = {key:index for index, key in enumerate(keys)}
    return map


def first_init():
    #初始化数据连接
    conn = db.connect("bot.db")
    cur = conn.cursor()
    #创建历史库
    sql = load_sql_from_file("sql/history.sql")
    cur.execute(sql)
    #创建索引
    sql = load_sql_from_file("sql/history_time_index.sql")
    cur.execute(sql)
    sql = load_sql_from_file("sql/analysis.sql")
    cur.execute(sql)
    cur.close()

@bot.command()
async def hello(context: Context):
    await context.send("Hello,{0}".format(str(context.author).split("#")[0]))


@bot.command()
async def collect_history(context: Context):
    await collect_history_msg(context)
    pass

async def find_last(conn, channel:TextChannel):
    cur = conn.cursor()
    try:
        sql = "select * from history where channel_id = {0} order by msg_id desc limit 1;"
        lastest = cur.execute(sql.format(channel.id))
        rs = lastest.fetchall()
        map = find_index(cur)
        after = None
        if rs is not None and len(rs) != 0:
            lastest_msg  = await channel.fetch_message(rs[0][map['msg_id']])
            after = discord_obj(lastest_msg.id)
        return after
    finally:
        cur.close()

async def collect_history_msg(context: Context):
    conn = db.connect("bot.db")
    try:
        cur = conn.cursor()
        f = open(config_file,'r',encoding='utf-8')
        config = yaml.load(f,Loader=yaml.FullLoader)
        ids = config['history']['collect_channel_ids']
        channels =  [channel for channel in bot.get_all_channels() if channel.id in ids]

        insert_sql = "insert into history(msg_id,content,user_name,user_id,bot,date_time,channel,channel_id)values(?,?,?,?,?,?,?,?);"

        for channel in channels:

            after = await find_last(conn, channel)

            msgs = []
            for msg in await channel.history(after=after, oldest_first=True).flatten():
                #channel, channel_id, 
                #msg.author.name  msg.author.bot
                if not msg.author.bot:
                    t = (msg.id, msg.content, msg.author.name, msg.author.id, msg.author.bot, msg.created_at, msg.channel.name, msg.channel.id)
                    msgs.append(t)
                if len(msgs) == config['history']['batch_insert_row']:
                    cur.executemany(insert_sql,msgs)
                    msgs = []

            #处理剩余的数据
            if len(msgs) > 0:
                cur.executemany(insert_sql,msgs)
            await context.author.send("完成{0}".format(channel.name))

            conn.commit()
    #except Exception:
    #    print(msgs)
    finally:
        f.close()
        conn.close()

    

@bot.command()
async def service_info(context: Context):
    channels = bot.get_all_channels()
    tmp = "channel_info:\n{0}"
    channel_info = ""
    for channel in channels:
        channel_info = channel_info + "channel_id:{0}, \tchannel_name:{1}, \tchannel_type:{2}\n".format(channel.id, channel.name, str(channel.__class__.__name__))
    service_info = tmp.format(channel_info)
    await context.author.send(service_info)

@bot.command()
async def show_user_info(context: Context):
    msg = "user name:\t{0}\nuser id:\t{1}".format(context.author.name, context.author.id)
    await context.author.send(msg)

@bot.command()
async def show_bot_info(context: Context):
    msg = "bot name:\t{0}\nbot user id:\t{1}".format(bot.user.name, bot.user.id)
    await context.author.send(msg)

#群发消息命令
@bot.command(name="bsm")
async def batch_send_msg(context: Context):
    f = open(config_file,'r',encoding='utf-8')
    file_content = None
    try:
        config = yaml.load(f,Loader=yaml.FullLoader)
        msg_file = config['batch_send_msg']['filename']
        file_content = open(msg_file,'r',encoding='utf-8')
        lines = file_content.readlines()
        total = len(lines)
        count = 0
        for line in lines:
            line = line.strip()
            params = line.split("|")
            #每行数据不是2个，说明格式有问题。不发送
            if len(params) != 2:
                pass
            user_id = params[0]
            msg = params[1]
            await bot.get_user(int(user_id)).send(msg)
            count += 1
            if count % int(config['batch_send_msg']['progress_tips']) == 0:
                await context.author.send("群发进行中，当前进度为: {0}/{1}".format(count, total))
            #当强制停止群发后，将标志重置，重新允许群发。并结束本次群发
            global force_stop_batch_send_msg 
            if force_stop_batch_send_msg:
                force_stop_batch_send_msg  = False
                await context.author.send("本次群发已经停止,停止时进度为: {0}/{1}".format(count,total))
                return
    except Exception as e:
        print("{0}error: {1}".format(e,line))
    finally:
        f.close()
        if file_content is not None:
            file_content.close()

#强制停止群发命令
@bot.command(name="force_stop_bsm")
async def force_stop_batch_send_func(context: Context):
    global force_stop_batch_send_msg 
    force_stop_batch_send_msg = True

@bot.command(name="analysis")
async def analysis(context: Context):
    conn = db.connect("bot.db")
    cur = conn.cursor() 
    try:
        cur.execute("DELETE FROM analysis")
        conn.commit()
        config = get_config()
        words = get_analysis_words()
        page_size = int(config['analysis']['page_size'])
        sql = "select * from history"
        insert_sql = "insert into analysis(msg_id,content,user_name,user_id,bot,date_time,channel,channel_id,keyword)values(?,?,?,?,?,?,?,?,?);"
        cur.execute(sql)
        map = find_index(cur)
        msgs = cur.fetchmany(page_size)
        cur_insert = conn.cursor()
        while(len(msgs)>0):
            insert_msgs = []
            for msg in msgs:
                content = msg[map['content']]
                match = False
                for word in words:
                    if not match and content.find(word) > -1:
                        insert_msg = [m for m in msg]
                        insert_msg.append(word)
                        insert_msgs.append(insert_msg)
                        match = True
            if len(insert_msgs) > 0:
                cur_insert.executemany(insert_sql, insert_msgs)
                conn.commit()
                insert_msgs = []
            msgs = cur.fetchmany(page_size)
        
        df = pd.read_sql("select * from analysis", conn)
        df.to_csv("output/analysis_result.csv",index=False)
        await context.author.send("分析完成")
    finally:
        conn.close()

def get_config():
    f = open(config_file,'r',encoding='utf-8')
    try:
        config = yaml.load(f,Loader=yaml.FullLoader)
        return config
    finally:
        f.close()

def get_analysis_words():
    filename = get_config()['analysis']['keyword_filename']
    f = open(filename,'r',encoding='utf-8')
    try:
        return [word.strip().replace("\n","").replace("\t","") for word in f.readlines() if word.strip() != ""]
    finally:
        f.close()
def init_pid():
    my_pid = os.getpid() 
    f_pid = open('bot.pid', 'w') 
    f_pid.write(str(my_pid))
    f_pid.close()

@bot.event
async def on_ready():
    print("机器人启动完毕")

def read_file_fisrt_line(path:str):
    f = open(path,"r",encoding="utf-8")
    try:
        return f.readline()
    finally:
        f.close()

print("机器人启动中")
init_pid()
config_file = "config/config.yml"
force_stop_batch_send_msg = False
token = read_file_fisrt_line("config/token.txt")
first_init()

bot.run(token)
