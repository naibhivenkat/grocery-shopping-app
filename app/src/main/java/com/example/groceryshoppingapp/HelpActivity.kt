package com.example.groceryshoppingapp

import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class HelpActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_help)

        val faqList = findViewById<LinearLayout>(R.id.ll_faq)
        val faqs = listOf(
            "How to reset my password?",
            "How to update my profile?",
            "How to place an order?",
            "How to contact support?"
        )

        faqs.forEach { question ->
            val tv = TextView(this)
            tv.text = question
            tv.textSize = 16f
            tv.setPadding(16, 16, 16, 16)
            tv.setTextColor(resources.getColor(android.R.color.black, theme))
            tv.setOnClickListener {
                Toast.makeText(this, "Open detailed help for: $question", Toast.LENGTH_SHORT).show()
            }
            faqList.addView(tv)
        }
    }
}
