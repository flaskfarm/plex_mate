from sqlalchemy import and_, desc, func, not_, or_

from .setup import *


class ModelScanItem(ModelBase):
    P = P
    __tablename__ = f'scan_item'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time    = db.Column(db.DateTime)
    filecheck_time  = db.Column(db.DateTime)    
    completed_time  = db.Column(db.DateTime)

    callback = db.Column(db.String)
    callback_id = db.Column(db.String)
    callback_url = db.Column(db.String)
    mode = db.Column(db.String) # add remove
    target = db.Column(db.String) # 입력받은 것 그대로
    target_type = db.Column(db.String) # file, folder
    target_section_id = db.Column(db.Integer) # 입력 받을 수도 있음. 같은 폴더가 여러 라이브러리에 있을 수 있음. 모든것을 다 스캔하기는 귀찮지만 이 섹션id를 요청하면 여기 아래 폴더만 찾음. 없다면 db 순서대로 하나 찾으면 끝
    flag_filecheck = db.Column(db.Boolean)
    flag_last_filecheck = db.Column(db.Boolean)
    flag_db_include = db.Column(db.Boolean)
    flag_cancel = db.Column(db.Boolean)
    flag_finish = db.Column(db.Boolean)
    
    scan_folder = db.Column(db.String)
    process_pid = db.Column(db.String)
    process_start_time = db.Column(db.DateTime)
    process_finish_time = db.Column(db.DateTime)
    process_duration = db.Column(db.Integer)
    status = db.Column(db.String)
    queue_list = []

    filecheck_count = db.Column(db.Integer)
    mediapart_id = db.Column(db.String)
    #metadata_title = db.Column(db.String)
    #metadata_type = db.Column(db.String)
    #metadata_item_id = db.Column(db.String)
    #show_metadata_item_id = db.Column(db.String)
    meta_info = db.Column(db.JSON)
    section_id = db.Column(db.String)
    section_type = db.Column(db.String)

    # 파일 체크 대상

    # 스캔 대상
    # run_add_find : 추가모드. 파일 찾음
    # run_remove_removed : 삭제모드 파일 없어짐

    # enqueue_remove_removed : 삭제모드 파일 없어짐
    # 완료
    # 
    # 있지 않음.
    # finish_wrong_section_id : 잘못된 섹션 ID로 요청
    
    # finish_remove_already_not_in_db : 삭제모드. 이미 DB에 파일이 없음. 완료
    # finish_already_scan_folder_exist : 추가나 삭제모드. 이미 스캔 대상 폴더가 DB에 있음
    
    # finish_remove : 삭제모드 끝

    # READY : 준비
    # ENQUEUE_ADD_FIND : 추가모드. 파일 찾음
    # SCANNING : 스캔중
    # FINISH_ADD : 정상추가
    # FINISH_ADD_ALREADY_IN_DB : 추가모드. 이미 DB에 파일이 있음
    # FINISH_ALREADY_IN_QUEUE : 이미 QUEUE에 scan_folder가 있음
    # FINISH_NOT_FIND_LIBRARY  : section_location에 없음. 
    # FINISH_TIMEOVER : 추가모드. 대기시간 지남

    def __init__(self, target, mode="ADD", target_section_id='0', callback_id=None, callback_url=None):
        self.mode = mode
        self.target = target
        self.target_section_id = target_section_id
        
        self.callback_id = callback_id
        if self.callback_id != None:
            self.callback = callback_id.rsplit('_', 1)[0]
        self.callback_url = callback_url

        self.created_time = datetime.now()
        self.status = "READY"
        self.flag_filecheck = False
        self.flag_last_filecheck = False
        self.flag_db_include = False
        self.flag_cancel = False
        self.flag_finish = False
        self.filecheck_count = 0
   


    @classmethod
    def make_query(cls, req, order='desc', search='', option1='all', option2='all'):
        with F.app.app_context():
            query = F.db.session.query(cls)
            query = cls.make_query_search(query, search, cls.target)
            if option1 == 'completed':
                query = query.filter_by(completed=True)
            elif option1 == 'incompleted':
                query = query.filter_by(completed=False)
            if order == 'desc':
                query = query.order_by(desc(cls.id))
            else:
                query = query.order_by(cls.id)
            return query 


    @classmethod
    def get_incompleted(cls):
        with F.app.app_context():
            return db.session.query(cls).filter_by(
                flag_finish=False
            ).all()
       

    ### only for queue
    def init_for_queue(self):
        self.queue_list.append(self)

    @classmethod
    def get_by_id_in_queue(cls, id):
        for _ in cls.queue_list:
            if _.id == int(id):
                return _
    
    @classmethod
    def remove_in_queue(cls, db_item):
        ret = []
        for _ in cls.queue_list:
            if _.id == db_item.id:
                continue
            ret.append(_)
        cls.queue_list = ret



    def set_status(self, status, save=False):
        self.status = status
        if status == 'ENQUEUE_ADD_FIND':
            self.filecheck_time = datetime.now()
            self.flag_filecheck = True
        elif status == 'SCANNING':
            self.process_start_time = datetime.now()
        elif status == 'FINISH_ADD':
            self.process_finish_time = datetime.now()
            self.process_duration = str(self.process_finish_time - self.process_start_time)
        if self.status.startswith('FINISH_'):
            self.completed_time = datetime.now()
            if self.callback_id != None and self.callback_url != None:
                try:
                    ret = requests.post(self.callback_url, data=self.as_dict()).text
                    logger.debug(f'scan callback : {ret}')
                except Exception as e: 
                    logger.error(f'Exception:{str(e)}')
                    #logger.error(traceback.format_exc())
            self.remove_in_queue(self)
        if save:
            self.save()


    @classmethod
    def get_list_by_status(cls, status):
        with F.app.app_context():
            query = db.session.query(cls).filter(
                cls.status == status,
            )
            query = query.order_by(cls.id)
            return query.all()


    @classmethod
    def set_status_incompleted_to_ready(cls):
        with F.app.app_context():
            ret = db.session.query(cls).filter(
                not_(cls.status.like('FINISH_%')),
                cls.mode == 'ADD'
            ).update({'status':'READY'}, synchronize_session="fetch")
            db.session.commit()
            return ret

    @classmethod
    def make_query(cls, req, order='desc', search='', option1='all', option2='all'):
        with F.app.app_context():
            query = cls.make_query_search(F.db.session.query(cls), search, cls.target)

            if option1 != 'all':
                query = query.filter(cls.callback == option1)
            
            if option2 != 'all':
                query = query.filter(cls.status == option2)

            if order == 'desc':
                query = query.order_by(desc(cls.id))
            else:
                query = query.order_by(cls.id)

            return query       


    """
    @classmethod
    def get_items(cls, mode):
        if mode == 'wait':
            query = db.session.query(cls).filter(or_(cls.status == 'ready', cls.status.like('wait_%')))
            
        elif mode == 'run':
            query = db.session.query(cls).filter(cls.status.like('run_%'))
        elif mode == 'all':
            query = db.session.query(cls)

        query = query.order_by(cls.id)
        #logger.debug(query)
        items = query.all()
        return items

    
    @classmethod
    def is_already_scan_folder_exist(cls, scan_folder):
        query = db.session.query(cls).filter(
            cls.scan_folder == scan_folder,
            or_(cls.status == 'run_add_find', cls.status == 'run_remove_removed')
        )
        query = query.order_by(cls.id)
        items = query.all()
        return items   

    @classmethod
    def not_finished_to_ready(cls):
        items = db.session.query(cls).filter(not_(cls.status.like('finish_%'))).with_for_update().all()
        for item in items:
            item.status = 'ready'
        db.session.commit()

       
    # JSON 
    

    """
    