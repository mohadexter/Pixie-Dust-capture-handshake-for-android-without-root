package ma.pixiedust.app.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import ma.pixiedust.app.R;

/** Four rising bars, filled according to the RSSI of the network. */
public class SignalBarsView extends View {

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF bar = new RectF();
    private int level = 1;
    private int activeColor;
    private int inactiveColor;
    private float radius;

    public SignalBarsView(Context context) {
        this(context, null);
    }

    public SignalBarsView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        activeColor = ContextCompat.getColor(context, R.color.indigo);
        inactiveColor = ContextCompat.getColor(context, R.color.line_strong);
        radius = Ui.dp(context, 1.5f);
    }

    public void setRssi(int rssi) {
        int next = Ui.signalLevel(rssi);
        if (next != level) {
            level = next;
            invalidate();
        }
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = resolveSize((int) Ui.dp(getContext(), 26), widthMeasureSpec);
        int height = resolveSize((int) Ui.dp(getContext(), 18), heightMeasureSpec);
        setMeasuredDimension(width, height);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int count = 4;
        float gap = Ui.dp(getContext(), 2f);
        float width = (getWidth() - gap * (count - 1)) / count;
        float height = getHeight();
        float[] fractions = {0.32f, 0.52f, 0.76f, 1f};
        for (int i = 0; i < count; i++) {
            float left = i * (width + gap);
            float barHeight = height * fractions[i];
            bar.set(left, height - barHeight, left + width, height);
            paint.setColor(i < level ? activeColor : inactiveColor);
            canvas.drawRoundRect(bar, radius, radius, paint);
        }
    }
}
