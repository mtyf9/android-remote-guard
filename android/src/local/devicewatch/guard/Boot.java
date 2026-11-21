package local.devicewatch.guard;
import android.content.*;
public class Boot extends BroadcastReceiver {
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction()))
            c.startForegroundService(new Intent(c, Guard.class));
    }
}
