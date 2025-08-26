package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class SplashActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 👇 Create a LinearLayout that centers its content
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT
            )
        }

        // 👇 Create the welcome text
        val welcomeText = TextView(this).apply {
            textSize = 22f
            text = when (BuildConfig.APP_ROLE) {
                "customer" -> "Welcome to Customer App"
                "shopowner" -> "Welcome to Shop Owner App"
                else -> "Welcome to Grocery App"
            }
            gravity = Gravity.CENTER
        }

        layout.addView(welcomeText)
        setContentView(layout)

        // ⏳ Delay before navigating to Login
        Handler(Looper.getMainLooper()).postDelayed({
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }, 2000)
    }
}
