package ma.pixiedust.app.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import ma.pixiedust.app.R;

/**
 * Six dots joined by segments: adapter, capture, PIN search, verify, PSK, done.
 * Completed steps are indigo, the current one is amber (red when the run failed).
 */
public class StepperView extends View {

    public static final int STEP_COUNT = 6;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int stepCount = STEP_COUNT;
    private int current = 0;
    private boolean failed;
    private boolean completed;

    private int indigo;
    private int amber;
    private int red;
    private int line;

    public StepperView(Context context) {
        this(context, null);
    }

    public StepperView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        indigo = ContextCompat.getColor(context, R.color.indigo);
        amber = ContextCompat.getColor(context, R.color.amber);
        red = ContextCompat.getColor(context, R.color.red);
        line = ContextCompat.getColor(context, R.color.line_strong);
    }

    public void setStep(int index, boolean failed, boolean completed) {
        int clamped = Math.max(0, Math.min(stepCount - 1, index));
        if (clamped == current && failed == this.failed && completed == this.completed) {
            return;
        }
        this.current = clamped;
        this.failed = failed;
        this.completed = completed;
        invalidate();
    }

    /** Handshake capture has five stages; the attack flow uses the default six. */
    public void setStepCount(int count) {
        int clamped = Math.max(2, count);
        if (clamped == stepCount) {
            return;
        }
        stepCount = clamped;
        current = Math.min(current, stepCount - 1);
        invalidate();
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = resolveSize(getSuggestedMinimumWidth(), widthMeasureSpec);
        int height = resolveSize((int) Ui.dp(getContext(), 26), heightMeasureSpec);
        setMeasuredDimension(width, height);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float padding = Ui.dp(getContext(), 6);
        float usable = getWidth() - padding * 2;
        if (usable <= 0) {
            return;
        }
        float gap = usable / (stepCount - 1);
        float centerY = getHeight() / 2f;
        float nodeRadius = Ui.dp(getContext(), 4.5f);
        boolean rtl = getLayoutDirection() == LAYOUT_DIRECTION_RTL;

        paint.setStrokeWidth(Ui.dp(getContext(), 2f));
        paint.setStrokeCap(Paint.Cap.ROUND);
        for (int i = 0; i < stepCount - 1; i++) {
            float x1 = x(i, gap, padding, rtl);
            float x2 = x(i + 1, gap, padding, rtl);
            paint.setColor(i < current ? indigo : line);
            canvas.drawLine(x1, centerY, x2, centerY, paint);
        }

        paint.setStrokeCap(Paint.Cap.BUTT);
        for (int i = 0; i < stepCount; i++) {
            float cx = x(i, gap, padding, rtl);
            int color;
            if (completed || i < current) {
                color = indigo;
            } else if (i == current) {
                color = failed ? red : amber;
            } else {
                color = line;
            }
            paint.setColor(color);
            canvas.drawCircle(cx, centerY, nodeRadius, paint);
        }
    }

    private float x(int index, float gap, float padding, boolean rtl) {
        int position = rtl ? (stepCount - 1 - index) : index;
        return padding + position * gap;
    }
}
