from .setup import *


class ModelPeriodicItem(ModelBase):
    P = P
    __tablename__ = 'periodic_item'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    mode = db.Column(db.String) # 스케쥴링에 의해 실행, 수동실행
    status = db.Column(db.String)

    section_id = db.Column(db.Integer)
    section_title = db.Column(db.String)
    section_type = db.Column(db.Integer)
    process_pid = db.Column(db.String)
    folder = db.Column(db.String)
    duration = db.Column(db.Integer)
    #result = db.Column(db.JSON, ensure_ascii=False)
    append_files = db.Column(db.String)
    start_time = db.Column(db.DateTime)
    finish_time = db.Column(db.DateTime)
    part_before_max = db.Column(db.Integer)
    part_before_count = db.Column(db.Integer)
    part_after_max = db.Column(db.Integer)
    part_after_count = db.Column(db.Integer)
    part_append_count = db.Column(db.Integer)
    

    def __init__(self):
        self.created_time = datetime.now()
        self.status = "ready"

    @classmethod
    def set_terminated(cls):
        try:
            with F.app.app_context():
                db.session.query(cls).filter(cls.status == 'working').update(dict(status='terminated'))
                db.session.commit()
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def remove_no_append_data(cls):
        with F.app.app_context():
            db.session.query(cls).filter(
                cls.status != 'working',
                or_(cls.part_append_count == 0, cls.part_append_count == None)
            ).delete()
            db.session.commit()
            return {'ret':'success', 'msg':'삭제하였습니다.'}


    @classmethod
    def make_query(cls, req, order='desc', search='', option1='all', option2='all'):
        with F.app.app_context():
            query = db.session.query(cls)
            query = cls.make_query_search(query, search, cls.append_files)
            if option1 != 'all':
                query = query.filter(cls.section_id == option1)
            if option2 == 'append':
                query = query.filter(cls.part_append_count > 0)
            if order == 'desc':
                query = query.order_by(desc(cls.id))
            else:
                query = query.order_by(cls.id)
            return query 


