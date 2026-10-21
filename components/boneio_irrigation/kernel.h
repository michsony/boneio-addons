#pragma once
#include <stdint.h>
#define IR_NAN __builtin_nanf("")
inline bool ir_finite(float v){return __builtin_isfinite(v);}
inline float ir_floor(float v){return __builtin_floorf(v);}
inline float ir_ceil(float v){return __builtin_ceilf(v);}
// Portable, allocation-free scheduler. Compiled unchanged for ESPHome and browser WebAssembly.
namespace boneio_irrigation {
inline int civil_day(int year,unsigned month,unsigned day){year-=month<=2;const int era=(year>=0?year:year-399)/400;const unsigned yoe=unsigned(year-era*400);const unsigned doy=(153*(month+(month>2?-3:9))+2)/5+day-1;return era*146097+int(yoe*365+yoe/4-yoe/100+doy)-719468;}
inline int civil_month(int day){int z=day+719468;int era=(z>=0?z:z-146096)/146097;unsigned doe=unsigned(z-era*146097),yoe=(doe-doe/1460+doe/36524-doe/146096)/365,doy=doe-(365*yoe+yoe/4-yoe/100),mp=(5*doy+2)/153;return int(mp+(mp<10?3:-9));}
struct Layout {
  int z,m,p,s;
  int zone(int i,int f=0)const{return 24+i*18+f;}
  int pump(int i,int f=0)const{return 24+z*18+i*12+f;}
  int program(int i,int f=0)const{return 24+z*18+m*12+i*12+f;}
  int member(int a,int b,int f=0)const{return 24+z*18+m*12+p*12+(a*z+b)*4+f;}
  int slot(int a,int b,int f=0)const{return member(p,0)+(a*s+b)*10+f;}
  int over(int a,int b,int c,int f=0)const{return slot(p,0)+((a*s+b)*z+c)*3+f;}
  int allow(int a,int b)const{return over(p,0,0)+a*m+b;}
  int size()const{return allow(z,0)+16;}
};
struct Hooks {
  void (*start)(int,uint32_t)=nullptr;
  void (*stop)(int)=nullptr;
  void (*emergency)()=nullptr;
  int (*busy)(int)=nullptr;
  int (*valve)(int)=nullptr;
  int (*pump)(int)=nullptr;
  float (*sensor)(int,int)=nullptr;
  // Must durably commit the deduplication claim BEFORE a scheduled run can energize hardware.
  bool (*commit)()=nullptr;
  void (*event)(int,int,int,double)=nullptr;
};
struct Job {
  int zone=-1,program=-1,priority=0,order=0,cycles=1;
  uint32_t remaining=0,soak=0,sequence=0;
  uint32_t run=0;
  double ready=0,expires=0;
  bool started=false;
};
struct Active {Job job;bool on=false,seen=false,cancel=false;double began=0,deadline=0,valveBegan=0;uint32_t chunk=0;};
struct Event {double epoch=0;int zone=-1,program=-1,code=0;};
template<int Z,int M,int P,int S,int C,int Q> class Engine {
public:
  struct Snapshot {
    uint32_t magic=0,signature=0;
    float values[C]{};
    int32_t fired[P*S]{};
    uint32_t zoneSeconds[Z]{},pumpSeconds[M+1]{},runs=0;
    double waterLiters=0,rainUntil=0,lastRun=0;
    int fault=0,lastReason=0;bool rainWasOn=false;
  } saved;
  float values[C]{};
  int32_t fired[P*S]{};
  uint32_t zoneSeconds[Z]{},pumpSeconds[M+1]{},runs=0;
  double waterLiters=0,rainUntil=0,lastRun=0;
  int fault=0,lastReason=0;bool rainWasOn=false;
  Layout l{};Hooks hooks{};
  Job queue[Q]{};int count=0,queueLimit=Q;
  Active active[Z]{};double pumpOff[M+1]{};
  double zoneFraction[Z]{},pumpFraction[M+1]{},pumpBegan[M+1]{};
  Event history[32]{};int historyCount=0;
  uint32_t sequence=0,signature=0;
  uint32_t runSequence=0,planned=0;double delivered=0;
  bool dirty=false;double dirtyAt=0,epoch=0,mono=0,lastMono=0;
  int date=0,weekday=0,dom=0,minute=0,lastDate=-1,lastMinute=-1;
  bool validTime=false,initialized=false;
  float get(int i)const{return i>=0&&i<l.size()?values[i]:0;}
  float z(int i,int f)const{return get(l.zone(i,f));}
  float m(int i,int f)const{return get(l.pump(i,f));}
  float p(int i,int f)const{return get(l.program(i,f));}
  bool occupied()const{if(count)return true;for(int i=0;i<l.z;i++)if(active[i].on)return true;return false;}
  bool moving()const{for(int i=0;i<l.z;i++)if(active[i].on)return true;return false;}
  bool zone_requested(int zone)const{if(zone>=0&&zone<l.z&&active[zone].on)return true;for(int i=0;i<count;i++)if(queue[i].zone==zone)return true;return false;}
  void event(int code,int zone=-1,int program=-1){lastReason=code;history[historyCount++%32]={epoch,zone,program,code};if(hooks.event)hooks.event(code,zone,program,epoch);}
  void mark(){dirty=true;dirtyAt=mono;}
  void init(Layout layout,uint32_t sig){l=layout;signature=sig;for(int i=0;i<P*S;i++)fired[i]=-1;initialized=true;}
  bool sane(int key,float v)const{
    if(!ir_finite(v)||key<0||key>=l.size())return false;
    if(key<24){switch(key){case 0:case 1:return v==0||v==1;case 2:return v>=0&&v<=300;case 4:return v>=1&&v<=86400;case 5:return v>=1&&v<=l.z;case 6:return v>=0&&v<=720;case 7:return v>=0&&v<=300;case 11:return v>=-50&&v<=80;default:return false;}}
    if(key<l.pump(0)){int f=(key-24)%18;switch(f){case 0:return v==0||v==1;case 1:case 2:case 3:return v>=1&&v<=86400;case 4:return v>=-1&&v<get(13);case 5:return v>=0&&v<=100;case 6:return v>=0&&v<=32;case 8:return v>=-1&&v<=3;case 9:return v>=0&&v<=127;case 10:return v>=1&&v<=365;case 11:return v>=0&&v<100000;case 12:case 13:return v>=0&&v<=86400;case 14:return v>=0&&v<=Z;case 16:return v>=0&&v<=100;default:return false;}}
    if(key<l.program(0)){int f=(key-l.pump(0))%12;if(f==0||f==3||f==4||f==8)return v==0||v==1;if(f==5||f==7)return v>=1&&v<=86400;return v>=0&&v<=86400;}
    if(key<l.member(0,0)){int f=(key-l.program(0))%12;if(f==0||f==7)return v==0||v==1;if(f==1)return v>=0&&v<=3;if(f==2)return v>=0&&v<=127;if(f==3)return v>=1&&v<=365;if(f==4)return v>=0&&v<100000;if(f==5)return v>=0&&v<=300;if(f==6)return v>=0&&v<=100;if(f==8||f==9)return v>=0&&v<=86400;return false;}
    if(key<l.slot(0,0)){int f=(key-l.member(0,0))%4;return f==0?(v==0||v==1):f==1?(v>=0&&v<=86400):f==2?(v>=0&&v<=Z):false;}
    if(key<l.over(0,0,0)){int f=(key-l.slot(0,0))%10;switch(f){case 0:return v==0||v==1;case 1:return v>=0&&v<=23;case 2:return v>=0&&v<=59;case 3:return v>=-1&&v<=3;case 4:return v>=0&&v<=127;case 5:return v>=1&&v<=365;case 6:return v>=0&&v<100000;case 7:case 8:return v>=-1&&v<=86400;default:return false;}}
    if(key<l.allow(0,0)){int f=(key-l.over(0,0,0))%3;return f==0?(v>=-1&&v<=1):f==1?(v>=0&&v<=86400):(v>=-1&&v<=Z);}
    return key>=l.allow(l.z,0)&&v>=0&&v<100000;
  }
  bool set(int key,float v){
    bool fractional=key==11||(key>=l.pump(0)&&key<l.program(0)&&(key-l.pump(0))%12>=9);
    if(!sane(key,v)||(!fractional&&ir_floor(v)!=v)){event(20);return false;}
    if(occupied()&&key!=0&&key!=1){event(21);return false;}
    if(key>=24&&key<l.pump(0)){
      int i=(key-24)/18,f=(key-24)%18;
      if(f==4&&v>=0&&!get(l.allow(i,int(v)))){event(22);return false;}
      if((f==1&&(v<z(i,2)||v>z(i,3)))||(f==2&&(v>z(i,1)||v>z(i,3)))||(f==3&&(v<z(i,1)||v<z(i,2)))){event(20);return false;}
    }
    values[key]=v;mark();if(key==0&&v==0)stop_all(2,false);return true;
  }
  const Snapshot &snapshot(){
    saved.magic=0x49525232;saved.signature=signature;
    for(int i=0;i<C;i++)saved.values[i]=values[i];
    for(int i=0;i<P*S;i++)saved.fired[i]=fired[i];
    for(int i=0;i<Z;i++)saved.zoneSeconds[i]=zoneSeconds[i];for(int i=0;i<M;i++)saved.pumpSeconds[i]=pumpSeconds[i];
    saved.runs=runs;saved.waterLiters=waterLiters;saved.rainUntil=rainUntil;saved.lastRun=lastRun;saved.fault=fault;saved.lastReason=lastReason;saved.rainWasOn=rainWasOn;return saved;
  }
  bool restore(){
    if(saved.magic!=0x49525232||saved.signature!=signature)return false;
    for(int i=0;i<l.size();i++)if(!ir_finite(saved.values[i]))return false;
    // Compile-time topology, safety feature flags and permitted pump matrix cannot be changed by restored data.
    for(int i=0;i<l.size();i++)if(sane(i,saved.values[i]))values[i]=saved.values[i];
    for(int i=0;i<P*S;i++)fired[i]=saved.fired[i];
    for(int i=0;i<Z;i++)zoneSeconds[i]=saved.zoneSeconds[i];for(int i=0;i<M;i++)pumpSeconds[i]=saved.pumpSeconds[i];
    runs=saved.runs;waterLiters=saved.waterLiters;rainUntil=saved.rainUntil;lastRun=saved.lastRun;fault=saved.fault;lastReason=saved.lastReason;rainWasOn=saved.rainWasOn;
    return true;
  }
  bool commit(){snapshot();if(hooks.commit&&!hooks.commit()){fault=8;stop_all(8,true);return false;}dirty=false;return true;}
  bool rain_delay(float hours){if(!validTime||hours<0||hours>720||!ir_finite(hours)){event(23);return false;}rainUntil=hours?epoch+hours*3600:0;mark();if(hours)stop_all(3,false);return commit();}
  void stop_all(int reason,bool hard){count=0;for(int i=0;i<l.z;i++)if(active[i].on){if(hooks.stop)hooks.stop(i);active[i].cancel=true;if(hard)active[i].on=false;}if(hard&&hooks.emergency)hooks.emergency();event(reason);mark();}
  void fail(int reason){fault=reason;stop_all(reason,true);commit();}
  void reset_fault(){if(moving())return;fault=0;event(0);mark();}
  void cancel_zone(int zone){for(int i=count-1;i>=0;i--)if(queue[i].zone==zone)erase(i);if(zone>=0&&zone<l.z&&active[zone].on){active[zone].cancel=true;if(hooks.stop)hooks.stop(zone);}event(4,zone);}
  void cancel_program(int program){for(int i=count-1;i>=0;i--)if(queue[i].program==program)erase(i);for(int z=0;z<l.z;z++)if(active[z].on&&active[z].job.program==program)cancel_zone(z);}
  void skip(){for(int i=0;i<l.z;i++)if(active[i].on){cancel_zone(i);return;}}
  void erase(int at){for(int j=at;j+1<count;j++)queue[j]=queue[j+1];count--;}
  bool day_matches(int mode,int mask,int every,int anchor)const{
    if(mode==0)return (mask&(1<<weekday))!=0;
    if(mode==1)return every>0&&date>=anchor&&(date-anchor)%every==0;
    if(mode==2)return dom%2==1&&dom!=31&&!(dom==29&&civil_month(date)==2);
    return mode==3&&dom%2==0;
  }
  bool days(int program,int slot,int zone)const{
    int mode=int(p(program,1)),mask=int(p(program,2)),every=int(p(program,3)),anchor=int(p(program,4));
    if(slot>=0&&get(l.slot(program,slot,3))>=0){mode=int(get(l.slot(program,slot,3)));mask=int(get(l.slot(program,slot,4)));every=int(get(l.slot(program,slot,5)));anchor=int(get(l.slot(program,slot,6)));}
    if(z(zone,8)>=0){mode=int(z(zone,8));mask=int(z(zone,9));every=int(z(zone,10));anchor=int(z(zone,11));}
    return day_matches(mode,mask,every,anchor);
  }
  float sensor(int type,int index=0)const{return hooks.sensor?hooks.sensor(type,index):IR_NAN;}
  bool permitted(int zone,bool weather=true){
    if(fault||!get(0)||!z(zone,0)){event(10,zone);return false;}
    if(rainUntil>0&&(!validTime||epoch<rainUntil)){event(3,zone);return false;}
    if(get(8)){float v=sensor(0);if(!ir_finite(v)){fail(7);return false;}if(v>0||(rainWasOn&&!validTime)){event(3,zone);return false;}}
    if(get(9)){float v=sensor(1);if(!ir_finite(v)||v>0){fail(6);return false;}}
    if(get(10)){float v=sensor(2);if(!ir_finite(v)){fail(7);return false;}if(v<get(11)){event(11,zone);return false;}}
    if(weather&&z(zone,7)){float v=sensor(3,zone);if(!ir_finite(v)||v>=z(zone,16)){event(12,zone);return false;}}
    int pump=int(z(zone,4));if(pump>=0&&(!m(pump,0)||m(pump,8)||!get(l.allow(zone,pump)))){event(22,zone);return false;}
    return true;
  }
  bool make_job(int program,int slot,int zone,Job &job,bool manual=false,uint32_t own=0){
    if(!permitted(zone))return false;
    if(!manual&&(!validTime||!days(program,slot,zone))){event(13,zone,program);return false;}
    float seconds=own?float(own):z(zone,1);int order=int(z(zone,14));
    if(program>=0){float v=get(l.member(program,zone,1));if(v>0)seconds=v;order=int(get(l.member(program,zone,2)));if(slot>=0){v=get(l.over(program,slot,zone,1));if(v>0)seconds=v;if(get(l.over(program,slot,zone,2))>=0)order=int(get(l.over(program,slot,zone,2)));}}
    seconds=ir_ceil(seconds*get(2)/100.0f*(program>=0?p(program,5)/100.0f:1.0f));
    if(seconds==0){event(14,zone,program);return false;}
    if(seconds<z(zone,2)||seconds>z(zone,3)){event(24,zone,program);return false;}
    float cycle=program>=0?p(program,8):z(zone,12),soak=program>=0?p(program,9):z(zone,13);
    if(program>=0&&cycle==0){cycle=z(zone,12);soak=z(zone,13);}
    if(slot>=0){float v=get(l.slot(program,slot,7));if(v>=0)cycle=v;v=get(l.slot(program,slot,8));if(v>=0)soak=v;}
    int cycles=cycle>0?int(ir_ceil(seconds/cycle)):1;
    int pump=int(z(zone,4));float minimum=z(zone,2);if(pump>=0&&m(pump,5)>minimum)minimum=m(pump,5);
    if(ir_floor(seconds/cycles)<minimum){event(24,zone,program);return false;}
    if(pump>=0&&ir_ceil(seconds/cycles)+m(pump,1)+m(pump,2)>m(pump,7)){event(25,zone,program);return false;}
    job.zone=zone;job.program=program;job.priority=int(z(zone,5))+(program>=0?int(p(program,6)):0);job.order=order;
    job.remaining=uint32_t(seconds);job.soak=uint32_t(soak);job.cycles=cycles;job.ready=mono;job.expires=mono+get(4);job.sequence=sequence++;return true;
  }
  bool enqueue_program(int program,int slot=-1,bool manual=true){
    if(program<0||program>=get(14)||!p(program,0)||fault)return false;
    if(p(program,7)&&occupied()){event(15,-1,program);return false;}
    if(occupied())event(18,-1,program);
    int wanted=0;for(int zone=0;zone<get(12);zone++){float member=get(l.member(program,zone));if(slot>=0&&get(l.over(program,slot,zone))>=0)member=get(l.over(program,slot,zone));Job j;if(member&&make_job(program,slot,zone,j,manual))wanted++;}
    if(count+wanted>queueLimit){event(16,-1,program);return false;}
    if(!occupied()){planned=0;delivered=0;}uint32_t run=++runSequence;
    for(int zone=0;zone<get(12);zone++){float member=get(l.member(program,zone));if(slot>=0&&get(l.over(program,slot,zone))>=0)member=get(l.over(program,slot,zone));Job j;if(member&&make_job(program,slot,zone,j,manual)){j.run=run;planned+=j.remaining;queue[count++]=j;}}
    return wanted>0;
  }
  bool manual_zone(int zone,uint32_t seconds=0){if(zone<0||zone>=get(12)||count>=queueLimit||zone_requested(zone))return false;Job job;if(!make_job(-1,-1,zone,job,true,seconds))return false;if(!occupied()){planned=0;delivered=0;}job.run=++runSequence;planned+=job.remaining;queue[count++]=job;return true;}
  bool manual_all(){if(count+get(12)>queueLimit){event(16);return false;}bool any=false;for(int i=0;i<get(12);i++)any=manual_zone(i)||any;return any;}
  bool can_start(const Job &job)const{
    if(active[job.zone].on)return false;
    int pump=int(z(job.zone,4)),running=0;
    if(pump>=0&&pumpOff[pump]>0&&mono-pumpOff[pump]<m(pump,6))return false;
    for(int i=0;i<l.z;i++)if(active[i].on){running++;if(z(i,6)==0||z(job.zone,6)==0||z(i,6)==z(job.zone,6)||(pump>=0&&int(z(i,4))==pump))return false;}
    return running<int(get(5));
  }
  void tick(double now,int civil,int week,int monthDay,int localMinute,double monotonic,bool valid){
    if(!initialized)return;
    epoch=now;date=civil;weekday=week;dom=monthDay;minute=localMinute;mono=monotonic;validTime=valid;
    if(!fault&&get(9)){float v=sensor(1);if(!ir_finite(v)||v>0){fail(6);return;}}
    if(!fault&&get(8)){
      float rain=sensor(0);if(!ir_finite(rain)){fail(7);return;}
      if(rain>0&&!rainWasOn){rainWasOn=true;stop_all(3,false);if(!commit())return;}
      if(rain<=0&&rainWasOn&&valid){rainWasOn=false;rainUntil=get(6)>0?epoch+get(6)*3600:0;mark();if(!commit())return;}
    }
    double dt=lastMono>0&&mono>=lastMono?mono-lastMono:0;lastMono=mono;
    for(int i=0;i<get(12);i++)if(active[i].on){
      auto &a=active[i];int pump=int(z(i,4));bool busy=hooks.busy&&hooks.busy(i);if(busy)a.seen=true;
      if(hooks.valve&&hooks.valve(i)){if(!a.valveBegan)a.valveBegan=mono;if(mono-a.valveBegan>z(i,3)){fail(26);return;}zoneFraction[i]+=dt;uint32_t whole=uint32_t(zoneFraction[i]);zoneSeconds[i]+=whole;zoneFraction[i]-=whole;if(pump<0||(hooks.pump&&hooks.pump(pump)))delivered+=dt;}
      if(mono>a.deadline){fail(26);return;}
      if(!a.seen&&mono>a.began+get(7)+(pump>=0?m(pump,1):0)+5){fail(27);return;}
      if(a.seen&&!busy){
        a.on=false;event(a.cancel?4:1,i,a.job.program);mark();
        if(pump>=0)pumpOff[pump]=mono;
        if(!a.cancel&&a.job.remaining>a.chunk){Job next=a.job;next.remaining-=a.chunk;next.cycles--;next.ready=mono+next.soak;next.started=true;next.sequence=sequence++;if(count<queueLimit)queue[count++]=next;else{fail(16);return;}}
      }
      if(!a.cancel&&!permitted(i)){if(fault)return;cancel_zone(i);}
    }
    for(int i=0;i<get(13);i++)if(hooks.pump&&hooks.pump(i)){
      if(!pumpBegan[i])pumpBegan[i]=mono;if(mono-pumpBegan[i]>m(i,7)){fail(25);return;}
      pumpFraction[i]+=dt;uint32_t whole=uint32_t(pumpFraction[i]);pumpSeconds[i]+=whole;pumpFraction[i]-=whole;float flow=sensor(5,i),pressure=sensor(4,i);
      if(ir_finite(flow)&&flow>0)waterLiters+=flow*dt/60.0;
      for(int a=0;a<l.z;a++)if(active[a].on&&int(z(a,4))==i){
        if(mono-active[a].began>m(i,7)){fail(25);return;}
        if(mono-active[a].began>get(7)+m(i,1)){
          if((m(i,9)>0&&(!ir_finite(pressure)||pressure<m(i,9)))||(m(i,10)>0&&(!ir_finite(flow)||flow<m(i,10)))||(m(i,11)>0&&(!ir_finite(flow)||flow>m(i,11)))){fail(28);return;}
        }
      }
    }else pumpBegan[i]=0;
    if(valid&&(civil!=lastDate||localMinute!=lastMinute)){
      lastDate=civil;lastMinute=localMinute;
      bool excluded=false;for(int i=0;i<16;i++)if(get(l.allow(l.z,0)+i)>0&&int(get(l.allow(l.z,0)+i))==civil)excluded=true;
      if(get(0)&&get(1)&&!fault&&!excluded)for(int p=0;p<get(14);p++)if(this->p(p,0))for(int s=0;s<l.s;s++){
        if(!get(l.slot(p,s))||int(get(l.slot(p,s,1)))*60+int(get(l.slot(p,s,2)))!=localMinute||fired[p*l.s+s]>=civil)continue;
        // Claim even a skipped/blocked start: no delayed catch-up after weather, reboot or clock rollback.
        fired[p*l.s+s]=civil;mark();if(!commit())return;
        enqueue_program(p,s,false);
      }
    }
    if(fault)return;
    for(int i=count-1;i>=0;i--)if(!queue[i].started&&mono>queue[i].expires){event(17,queue[i].zone,queue[i].program);erase(i);}
    for(int turn=0;turn<l.z;turn++){
      int best=-1;for(int i=0;i<count;i++)if(queue[i].ready<=mono&&can_start(queue[i])){if(best<0||queue[i].priority>queue[best].priority||(queue[i].priority==queue[best].priority&&(queue[i].order<queue[best].order||(queue[i].order==queue[best].order&&queue[i].sequence<queue[best].sequence))))best=i;}
      if(best<0)break;
      Job job=queue[best];erase(best);if(!permitted(job.zone))continue;
      for(int i=0;i<count;i++)if(queue[i].run==job.run)queue[i].started=true;
      job.started=true;
      auto &a=active[job.zone];a=Active{};a.on=true;a.job=job;a.began=mono;a.chunk=(job.remaining+job.cycles-1)/job.cycles;
      int pump=int(z(job.zone,4));a.deadline=mono+a.chunk+(pump>=0?m(pump,1)+m(pump,2):0)+get(7)+5;
      runs++;lastRun=epoch;event(30,job.zone,job.program);mark();if(hooks.start)hooks.start(job.zone,a.chunk);
    }
  }
  uint32_t remaining()const{uint32_t seconds=0;for(int i=0;i<count;i++)seconds+=queue[i].remaining;for(int i=0;i<l.z;i++)if(active[i].on){double passed=mono-active[i].began;seconds+=active[i].job.remaining>passed?uint32_t(active[i].job.remaining-passed):0;}return seconds;}
  bool scheduled_at(int day,int week,int md,int min){
    if(!get(0)||!get(1)||fault)return false;for(int i=0;i<16;i++)if(get(l.allow(l.z,0)+i)>0&&int(get(l.allow(l.z,0)+i))==day)return false;
    int saveDate=date,saveWeek=weekday,saveDom=dom;date=day;weekday=week;dom=md;bool result=false;
    for(int pr=0;pr<get(14)&&!result;pr++)if(p(pr,0))for(int s=0;s<l.s&&!result;s++)if(get(l.slot(pr,s))&&int(get(l.slot(pr,s,1)))*60+int(get(l.slot(pr,s,2)))==min&&fired[pr*l.s+s]<day)for(int zo=0;zo<get(12)&&!result;zo++){float member=get(l.over(pr,s,zo));if(member<0)member=get(l.member(pr,zo));if(member&&z(zo,0)&&days(pr,s,zo))result=true;}
    date=saveDate;weekday=saveWeek;dom=saveDom;return result;
  }
};
}
