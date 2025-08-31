package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityThankYouBinding
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager

class ThankYouActivity : AppCompatActivity() {
    private lateinit var binding: ActivityThankYouBinding
    private var customerId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityThankYouBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // ✅ Get customerId from SessionManager
        customerId = SessionManager.getCustomerId(this)

        // ✅ Optional: Get customer name from session for personalization
        val customerName = SessionManager.getUsername(this) ?: "Customer"
        binding.textViewThankYou.text = "Thank you, $customerName! Your order has been placed."

        // ✅ Log for debug
        Log.d("ThankYouActivity", "Loaded customerId: $customerId, customerName: $customerName")

        // ✅ Clear cart (optional)
        CartManager.clearAllCarts()

        // ✅ Back to home with cleared activity stack
        binding.buttonBackToHome.setOnClickListener {
            val intent = Intent(this, CustomerHomeActivity::class.java)
            intent.putExtra("customer_id", customerId) // optional
            intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            startActivity(intent)
        }
    }
}
