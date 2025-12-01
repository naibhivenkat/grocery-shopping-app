package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.drawerlayout.widget.DrawerLayout
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.navigation.NavigationView
import android.widget.Button

class CustomerHomeActivity : AppCompatActivity() {

    private var customerId:  String? = null
    private lateinit var drawerLayout: DrawerLayout
    private lateinit var navigationView: NavigationView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_customer_home)

        // Get logged-in customer ID
        customerId = SessionManager.getCustomerId(this)

        // Setup drawer + toolbar
        drawerLayout = findViewById(R.id.drawer_layout)
        navigationView = findViewById(R.id.navigation_view)
        val toolbar: Toolbar = findViewById(R.id.toolbar)

        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeAsUpIndicator(R.drawable.ic_menu)

        // Toggle drawer on menu click
        toolbar.setNavigationOnClickListener {
            if (drawerLayout.isDrawerOpen(Gravity.END)) {
                drawerLayout.closeDrawer(Gravity.END)
            } else {
                drawerLayout.openDrawer(Gravity.END)
            }
        }

        // --- MAIN BUTTONS ---
        findViewById<Button>(R.id.btn_select_shop).setOnClickListener {
            startActivity(Intent(this, ShopSelectionActivity::class.java))
        }

        findViewById<Button>(R.id.btn_view_orders).setOnClickListener {
            startActivity(Intent(this, CustomerOrdersActivity::class.java))
        }

        // ------------- NAV DRAWER MENU CLICK HANDLER -------------
        navigationView.setNavigationItemSelectedListener { menuItem ->
            when (menuItem.itemId) {

                R.id.nav_view_profile ->
                    startActivity(Intent(this, ProfileActivity::class.java))

                R.id.nav_settings ->
                    startActivity(Intent(this, SettingsActivity::class.java))

                R.id.nav_wallet ->
                    startActivity(Intent(this, WalletActivity::class.java))

                // 🔥 NEW — KHATA BOOK / ACCOUNT MANAGER
                R.id.nav_my_khata ->
                    startActivity(Intent(this, CustomerKhataListActivity::class.java))


                R.id.nav_logout -> {
                    SessionManager.logout(this)
                    val intent = Intent(this, LoginActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                    startActivity(intent)
                }
            }

            drawerLayout.closeDrawer(Gravity.END)
            true
        }
    }

    override fun onBackPressed() {
        if (drawerLayout.isDrawerOpen(Gravity.END)) {
            drawerLayout.closeDrawer(Gravity.END)
        } else {
            super.onBackPressed()
        }
    }
}
