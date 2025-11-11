package com.example.groceryshoppingapp.customer

import com.example.groceryshoppingapp.CustomerActivity
import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class CustomerLauncher : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startActivity(Intent(this, CustomerActivity::class.java))
        finish()
    }
}
