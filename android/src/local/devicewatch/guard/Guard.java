package local.devicewatch.guard;

import android.app.*;
import android.content.*;
import android.hardware.*;
import android.os.*;
import android.util.Log;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.*;
import java.io.*;
import java.net.*;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.util.*;
import java.util.concurrent.*;
import javax.net.ssl.*;

public class Guard extends Service {
    final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
    final Map<String,Long> last=new HashMap<>();
    SensorManager sensors;
    Sensor motion;
    PowerManager.WakeLock wake;
    boolean watching;
    volatile boolean destroyed;
    volatile int lastStart;
    SSLSocketFactory sockets;
    String token;
    SQLiteDatabase pending;
    final java.util.concurrent.atomic.AtomicBoolean flushScheduled=new java.util.concurrent.atomic.AtomicBoolean();
    String endpoint;
    static JSONObject profile(Context c){
        try(Scanner in=new Scanner(c.openFileInput("device.json"),"UTF-8")){return new JSONObject(in.useDelimiter("\\A").next());}
        catch(Exception ex){return new JSONObject();}
    }
    public static boolean armed(Context c) {return c.getSharedPreferences("guard",0).getBoolean("armed",true);}
    static void setMode(Context c,boolean enabled,String request){
        SharedPreferences prefs=c.getSharedPreferences("guard",0);
        boolean change=armed(c)!=enabled;
        Intent intent=new Intent(c,Guard.class);
        SharedPreferences.Editor update=prefs.edit().putString("mode_ack",UUID.randomUUID().toString());
        if(request==null || !request.equals(prefs.getString("mode_request",""))){
            update.putBoolean("armed",enabled);
            if(request!=null)update.putString("mode_request",request);
            if(change)intent.setAction(enabled?"armed":"disarmed");
        }
        if(!update.commit())return;
        intent.putExtra("server_mode",request!=null);
        c.startForegroundService(intent.putExtra("report_mode",true));
    }
    final TriggerEventListener trigger=new TriggerEventListener(){
        public void onTrigger(TriggerEvent e){
            long age=(SystemClock.elapsedRealtimeNanos()-e.timestamp)/1000000L;
            event("movement",System.currentTimeMillis()-Math.max(0,age));
            if(watching)sensors.requestTriggerSensor(this,motion);
        }
    };
    public IBinder onBind(Intent i){return null;}
    public void onCreate(){
        super.onCreate();
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("monitor","布防状态",NotificationManager.IMPORTANCE_LOW));
        startForeground(1,new Notification.Builder(this,"monitor").setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle(profile(this).optString("name","受控端")+" · 布防服务").setContentText("正在监测或投递事件")
            .setContentIntent(PendingIntent.getActivity(this,0,new Intent(this,Main.class),PendingIntent.FLAG_IMMUTABLE)).build());
        sensors=getSystemService(SensorManager.class);motion=sensors.getDefaultSensor(Sensor.TYPE_SIGNIFICANT_MOTION);
        wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"DeviceWatch:monitor");
        pending=openOrCreateDatabase("outbox.db",MODE_PRIVATE,null);
        pending.execSQL("CREATE TABLE IF NOT EXISTS alerts(id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)");
        migrateQueue();
        watch();
        worker.scheduleWithFixedDelay(this::flush,3,60,TimeUnit.SECONDS);
    }
    void watch(){
        if(armed(this)==watching)return;
        watching=armed(this);
        if(watching){
            wake.acquire();
            if(motion==null||!sensors.requestTriggerSensor(trigger,motion))Log.w("DeviceWatch","Motion sensor unavailable");
        }else{release();}
    }
    void release(){if(motion!=null)sensors.cancelTriggerSensor(trigger,motion);if(wake.isHeld())wake.release();}
    public int onStartCommand(Intent i,int flags,int id){
        lastStart=id;
        watch();
        if(i!=null && i.hasExtra("report_mode") && i.getAction()==null)worker.execute(this::flush);
        if(i!=null && i.getAction()!=null){
            if(!armed(this) && !Arrays.asList("armed","disarmed","test").contains(i.getAction()))return START_STICKY;
            long now=System.currentTimeMillis();
            long occurred=i.getLongExtra("occurred_ms",now);
            long kernel=i.getLongExtra("kernel_us",0)/1000L;
            if(kernel>1000000000000L) occurred=kernel;
            else if(kernel>0) occurred=now-Math.max(0,System.nanoTime()/1000000L-kernel);
            event(i.getAction(),occurred,i.getBooleanExtra("server_mode",false));
        }
        return START_STICKY;
    }
    void event(String kind,long occurred){
        event(kind,occurred,false);
    }
    void event(String kind,long occurred,boolean serverMode){
        if(destroyed)return;
        long now=occurred;
        long gap="movement".equals(kind)?30000:1000;
        Long previous=last.get(kind);
        if(!kind.equals("armed") && !kind.equals("disarmed") && previous!=null && now>=previous && now-previous<gap)return;
        last.put(kind,now);
        try {
            persist(message(kind).put("time",occurred/1000).put("occurred_ms",occurred).put("server_mode",serverMode));
            if(flushScheduled.compareAndSet(false,true)) worker.execute(()->{
                try { flush(); } finally { flushScheduled.set(false); }
            });
        } catch(JSONException ex){Log.e("DeviceWatch","Queue error",ex);}
    }
    void persist(JSONObject event)throws JSONException {
        pending.execSQL("INSERT OR IGNORE INTO alerts VALUES(?,?)",new Object[]{event.getString("id"),event.toString()});
    }
    void migrateQueue(){
        SharedPreferences prefs=getSharedPreferences("guard",0);
        if(!prefs.contains("queue"))return;
        try {
            JSONArray old=new JSONArray(prefs.getString("queue","[]"));
            pending.beginTransaction();
            try {
                for(int i=0;i<old.length();i++)persist(old.getJSONObject(i));
                pending.setTransactionSuccessful();
            } finally {pending.endTransaction();}
            prefs.edit().remove("queue").commit();
        } catch(JSONException ex){Log.e("DeviceWatch","Previous queue could not be read",ex);}
    }
    JSONObject message(String kind)throws JSONException{
        Intent b=registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        return new JSONObject().put("id",UUID.randomUUID().toString()).put("kind",kind)
                .put("time",System.currentTimeMillis()/1000).put("armed",armed(this)).put("mode_protocol",1)
                .put("battery",b==null?-1:b.getIntExtra("level",-1))
                .put("powered",b!=null && b.getIntExtra("plugged",0)!=0);
    }
    void flush(){
        int start=lastStart;
        try{while(!destroyed){
                JSONObject event;
                try(Cursor row=pending.rawQuery("SELECT payload FROM alerts ORDER BY rowid LIMIT 1",null)){
                    if(!row.moveToFirst())break;
                    event=new JSONObject(row.getString(0));
                }
                if(!"screen_off".equals(event.optString("kind")))send(event);
                pending.delete("alerts","id=?",new String[]{event.getString("id")});
            }
            if(!destroyed){
                SharedPreferences prefs=getSharedPreferences("guard",0);
                Map<String,?> mode=prefs.getAll();
                boolean enabled=!Boolean.FALSE.equals(mode.get("armed"));
                String ack=(String)mode.get("mode_ack");
                if(enabled || ack!=null){
                    send(message(ack==null?"heartbeat":"mode_status").put("armed",enabled)
                        .put("mode_request",mode.get("mode_request")==null?"":mode.get("mode_request")));
                }
                new Handler(Looper.getMainLooper()).post(()->{
                    if(destroyed)return;
                    if(ack!=null && ack.equals(prefs.getString("mode_ack",null)))
                        prefs.edit().remove("mode_ack").commit();
                    if(!armed(this) && !prefs.contains("mode_ack") && start==lastStart)stopSelfResult(start);
                });
            }
        }catch(Exception ex){Log.w("DeviceWatch","Delivery pending: "+ex.getClass().getSimpleName());}
    }
    void send(JSONObject obj)throws Exception{
        if(sockets==null){
            KeyStore store=KeyStore.getInstance(KeyStore.getDefaultType());store.load(null);
            try(InputStream in=openFileInput("cert.pem")){store.setCertificateEntry("receiver",CertificateFactory.getInstance("X.509").generateCertificate(in));}
            TrustManagerFactory tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tm.init(store);
            SSLContext ctx=SSLContext.getInstance("TLS");ctx.init(null,tm.getTrustManagers(),null);
            try(BufferedReader r=new BufferedReader(new InputStreamReader(openFileInput("token"),"UTF-8"))){token=r.readLine();}
            sockets=ctx.getSocketFactory();
        }
        LinkedHashSet<String> addresses=new LinkedHashSet<>();
        if(endpoint!=null)addresses.add(endpoint);
        JSONArray servers=profile(this).getJSONArray("servers");
        for(int i=0;i<servers.length();i++)addresses.add(servers.getString(i));
        for(String address:addresses){
            HttpsURLConnection c=(HttpsURLConnection)new URL("https://"+address+":18761/v1/report").openConnection(Proxy.NO_PROXY);
            try{
                c.setSSLSocketFactory(sockets);c.setInstanceFollowRedirects(false);c.setConnectTimeout(3500);c.setReadTimeout(5000);
                c.setDoOutput(true);c.setRequestMethod("POST");c.setRequestProperty("Authorization","Bearer "+token);
                c.setRequestProperty("Content-Type","application/json");
                try(OutputStream out=c.getOutputStream()){out.write(obj.toString().getBytes("UTF-8"));}
                if(c.getResponseCode()!=204)throw new IOException("report rejected");
                endpoint=address;return;
            }catch(IOException ex){Log.w("DeviceWatch","Endpoint unavailable");}finally{c.disconnect();}
        }
        throw new IOException("No reachable server");
    }
    public void onDestroy(){destroyed=true;if(watching)release();worker.execute(()->pending.close());worker.shutdown();super.onDestroy();}
}
